"""Re-render a selection from the PDF it shows, at a higher resolution than the screen.

A screenshot only holds screen pixels, but a PDF holds vector text and graphics.
Okular reports each window's document and page over D-Bus. The selection's
pixels are then located on candidate pages by normalized cross-correlation,
first coarsely over a range of zoom levels and then precisely around the best
one. The located area is rendered again with Poppler, which Okular also uses.

Okular sizes pages from the screen's physical DPI, which can differ between
the axes, so pages may be a few percent wider or taller than their true
aspect. The precise search therefore fits horizontal and vertical zoom
separately, and the new render uses both.
"""
import dataclasses
import functools
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import cairo
import gi
import numpy as np

gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Poppler', '0.18')
from gi.repository import GdkPixbuf, Gio, GLib, Poppler  # noqa: E402

# Wrong pages of real slides scored at most 0.33, and an unrelated test page with
# a similar large black shape 0.64; true matches of small text at low zoom
# scored 0.84.
MATCH_THRESHOLD = .7
# The precise check stops after its first round below this score. Wrong pages
# of real slides reached 0.33; right ones climb far above it.
HOPELESS = .45
# A page this good ends the search; below it, neighboring pages are compared,
# since Beamer's step-by-step slides repeat most of a page.
CERTAIN = .9
SEARCH_TIMEOUT = 30  # Seconds before a search gives up on the remaining pages.
MIN_CONTRAST = 2  # Standard deviation, in gray levels, below which a page area counts as flat.
COARSE_SIZE = 64  # Longest template side for the zoom search, in pixels.
COARSE_STEP = 1.06  # Zoom ratio between coarse levels.
CANDIDATES = 3  # Coarse positions checked precisely.
FINE_SIZE = 400  # Longest template side for the precise match.
FINE_RANGE = .1  # The precise search stays within this zoom ratio of the coarse match.
FINE_STEPS = (.02, .01, .005, .0025)  # Hill-climbing step sizes, as zoom ratios.
MAX_STRETCH = .06  # Largest difference between horizontal and vertical zoom; Okular's was 0.04.
MAX_SCALE = 5.5  # Screen pixels per PDF point; Okular at 400 % on a 1x screen is about 5.3.
MAX_COARSE_PAGE = 1600  # Longest side of the coarse page image.


@dataclass(frozen=True)
class Source:
    path: str
    page: int  # Zero-based.
    scale_x: float  # Crop pixels per PDF point.
    scale_y: float
    x: float  # PDF point at the crop's top-left corner.
    y: float
    inverted: bool  # Okular showed the page with inverted colors.
    score: float

    @property
    def label(self):
        return f'{self.path.rsplit("/", 1)[-1]} p. {self.page + 1}'


@functools.lru_cache(maxsize=8)
def document(path):
    return Poppler.Document.new_from_gfile(Gio.File.new_for_path(path), None, None)


def gray(surface):
    """Luminance of an RGB24 or ARGB32 cairo surface as a float array."""
    surface.flush()
    width, height, stride = surface.get_width(), surface.get_height(), surface.get_stride()
    data = np.frombuffer(surface.get_data(), np.uint8).reshape(height, stride)[:, :width * 4]
    pixels = data.reshape(height, width, 4).astype(np.float32)
    # Cairo stores native-endian BGRA on little-endian machines.
    return pixels[..., 2] * .299 + pixels[..., 1] * .587 + pixels[..., 0] * .114


def gray_pixbuf(pixbuf):
    """Luminance of a GdkPixbuf as a float array."""
    width, height = pixbuf.get_width(), pixbuf.get_height()
    stride, channels = pixbuf.get_rowstride(), pixbuf.get_n_channels()
    data = pixbuf.get_pixels()
    data += bytes(height * stride - len(data))  # The last row has no padding.
    pixels = np.frombuffer(data, np.uint8).reshape(height, stride)[:, :width * channels]
    pixels = pixels.reshape(height, width, channels).astype(np.float32)
    return pixels[..., 0] * .299 + pixels[..., 1] * .587 + pixels[..., 2] * .114


def surface_from_gray(values):
    channel = np.clip(values, 0, 255).astype(np.uint8)
    height, width = channel.shape
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    stride = surface.get_stride()
    data = np.ndarray((height, stride // 4, 4), np.uint8, buffer=surface.get_data())
    data[:, :width, 0] = data[:, :width, 1] = data[:, :width, 2] = channel
    surface.mark_dirty()
    return surface


def resized(values, factor, factor_y=None):
    """Box-filtered resize of a grayscale array through cairo."""
    factor_y = factor if factor_y is None else factor_y
    if factor == factor_y == 1:
        return values
    source = surface_from_gray(values)
    width = max(1, round(values.shape[1] * factor))
    height = max(1, round(values.shape[0] * factor_y))
    target = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(target)
    context.scale(width / values.shape[1], height / values.shape[0])
    context.set_source_surface(source)
    context.get_source().set_filter(cairo.FILTER_GOOD)
    context.paint()
    return gray(target)


def render_page(page, scale, x=0, y=0, width=None, height=None):
    """Grayscale render of a page area. scale is pixels per point; x and y are pixels."""
    page_w, page_h = page.get_size()
    width = width or max(1, round(page_w * scale))
    height = height or max(1, round(page_h * scale))
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(surface)
    context.set_source_rgb(1, 1, 1)
    context.paint()
    context.translate(-x, -y)
    context.scale(scale, scale)
    page.render(context)
    return gray(surface)


def fast_length(n):
    """Smallest length of at least n with only 2, 3, and 5 as factors; FFTs of primes are slow."""
    while True:
        m = n
        for factor in (2, 3, 5):
            while m % factor == 0:
                m //= factor
        if m == 1:
            return n
        n += 1


def ncc(image, template):
    """Normalized cross-correlation of template at every position fully inside image."""
    height, width = image.shape
    t_h, t_w = template.shape
    if t_h > height or t_w > width:
        return None
    centered = template - template.mean()
    norm = math.sqrt(float((centered ** 2).sum()))
    if norm < 1e-3:
        return None
    # Zero padding beyond the image only affects positions that are cut off below.
    shape = (fast_length(height), fast_length(width))
    spectrum = np.fft.rfft2(image, shape) * np.fft.rfft2(centered[::-1, ::-1], shape)
    correlation = np.fft.irfft2(spectrum, shape)[t_h - 1:height, t_w - 1:width]

    def window_sums(values):
        # Float64 throughout: float32 sums over large white areas lose enough
        # precision to produce scores far above 1.
        table = np.zeros((height + 1, width + 1))
        table[1:, 1:] = values.cumsum(0, dtype=np.float64).cumsum(1)
        return table[t_h:, t_w:] - table[:-t_h, t_w:] - table[t_h:, :-t_w] + table[:-t_h, :-t_w]
    count = t_h * t_w
    image = image.astype(np.float64)
    variance = window_sums(image ** 2) - window_sums(image) ** 2 / count
    # Nearly flat page areas cannot match a template with contrast.
    flat = variance < count * MIN_CONTRAST ** 2
    scores = correlation / (np.sqrt(np.maximum(variance, 1e-9)) * norm)
    return np.clip(np.where(flat, 0, scores), -1, 1)


def best(scores):
    index = np.unravel_index(np.argmax(scores), scores.shape)
    return float(scores[index]), int(index[1]), int(index[0])


def coarse_candidates(template, page, base, base_scale, coarse):
    """Best (score, template pixels per point, x, y in points) at each zoom level, best first."""
    page_w, page_h = page.get_size()
    small = resized(template, coarse)
    found = []
    # Start at the smallest zoom where the selection still fits on the page.
    scale = max(template.shape[1] / page_w, template.shape[0] / page_h) * coarse
    while scale <= MAX_SCALE * coarse:
        image = base if scale >= base_scale else resized(base, scale / base_scale)
        ratio = image.shape[1] / base.shape[1] * base_scale  # Actual pixels per point after rounding.
        scores = ncc(image, small)
        if scores is not None:
            score, x, y = best(scores)
            found.append((score, ratio / coarse, x / ratio, y / ratio))
        if scale >= base_scale:
            break
        scale *= COARSE_STEP
    found.sort(reverse=True)
    distinct = []
    for candidate in found:
        # Neighboring zoom levels usually find the same spot; keep one of each.
        if all(abs(candidate[1] / other[1] - 1) > .1 or abs(candidate[2] - other[2]) > 5
               or abs(candidate[3] - other[3]) > 5 for other in distinct):
            distinct.append(candidate)
        if len(distinct) == CANDIDATES:
            break
    return distinct


def refine(template, page, candidate):
    """Precise (score, scale_x, scale_y, x, y) near a coarse candidate.

    One render above the candidate's zoom is resized to each tried pair of
    horizontal and vertical zoom levels, which is much faster than asking
    Poppler every time. The render is at the template's own size so both
    shrink through the same filter. Hill climbing then halves its step until
    neighbors stop improving the score.
    """
    _, coarse_scale, coarse_x, coarse_y = candidate
    fine = min(1, FINE_SIZE / max(template.shape))
    detail = resized(template, fine)
    top_scale = coarse_scale * (1 + FINE_RANGE)
    pad = .15 * max(template.shape) + 4
    left, top = round(coarse_x * top_scale - pad), round(coarse_y * top_scale - pad)
    region = render_page(page, top_scale, left, top,
                         round(template.shape[1] * (1 + FINE_RANGE) + 2 * pad),
                         round(template.shape[0] * (1 + FINE_RANGE) + 2 * pad))
    scores = {}

    def evaluate(ratio_x, ratio_y):
        """Score zoom levels given as ratios to the coarse zoom."""
        key = (round(ratio_x, 5), round(ratio_y, 5))
        if key not in scores:
            image = resized(region, ratio_x / (1 + FINE_RANGE) * fine, ratio_y / (1 + FINE_RANGE) * fine)
            correlation = ncc(image, detail)
            if correlation is None:
                scores[key] = None
            else:
                score, x, y = best(correlation)
                # Actual pixels per point after rounding the resized image.
                scale_x = top_scale * image.shape[1] / region.shape[1]
                scale_y = top_scale * image.shape[0] / region.shape[0]
                scores[key] = (score, scale_x / fine, scale_y / fine,
                               (left * image.shape[1] / region.shape[1] + x) / scale_x,
                               (top * image.shape[0] / region.shape[0] + y) / scale_y)
        return scores[key]

    current = (1, 1)
    result = evaluate(*current)
    for step in FINE_STEPS:
        improved = True
        while improved:
            improved = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                ratio = (current[0] + dx * step, current[1] + dy * step)
                if (not all(1 - FINE_RANGE <= value <= 1 + FINE_RANGE for value in ratio)
                        or abs(ratio[0] / ratio[1] - 1) > MAX_STRETCH):
                    continue
                trial = evaluate(*ratio)
                if trial and (not result or trial[0] > result[0]):
                    current, result, improved = ratio, trial, True
        if not result or result[0] < HOPELESS:
            break  # A wrong spot; finer steps will not rescue it.
    return result


def locate(template, page):
    """Find the template on a page; returns (score, scale_x, scale_y, x, y, inverted) or None.

    The scales are template pixels per point, and x and y are the template's
    top-left corner in points.
    """
    if template.std() < 4:
        return None  # Nothing distinctive to match.
    page_w, page_h = page.get_size()
    coarse = min(1, COARSE_SIZE / max(template.shape))
    base_scale = min(MAX_SCALE * coarse, MAX_COARSE_PAGE / max(page_w, page_h))
    base = render_page(page, base_scale)
    # Inverted colors are Okular's dark reading mode; try them only when needed.
    for inverted, candidate_template in enumerate((template, 255 - template)):
        matches = [refine(candidate_template, page, candidate)
                   for candidate in coarse_candidates(candidate_template, page, base, base_scale, coarse)]
        matches = [match for match in matches if match and match[0] >= MATCH_THRESHOLD]
        if matches:
            return (*max(matches), bool(inverted))
    return None


def call(bus, name, method, signature):
    return bus.call_sync(name, '/okular', 'org.kde.okular', method, None, GLib.VariantType(signature),
                         Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]


def visible_pids():
    """Okular-or-not process IDs with a window on screen, focused first; None without Niri."""
    try:
        windows = json.loads(subprocess.run(['niri', 'msg', '--json', 'windows'], capture_output=True,
                                            timeout=2, check=True).stdout)
        workspaces = json.loads(subprocess.run(['niri', 'msg', '--json', 'workspaces'], capture_output=True,
                                               timeout=2, check=True).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    active = {workspace['id'] for workspace in workspaces if workspace['is_active']}
    shown = [window for window in windows if window['workspace_id'] in active]
    shown.sort(key=lambda window: not window['is_focused'])
    return [window['pid'] for window in shown]


def okular_pages():
    """(document path, zero-based page) pairs for Okular windows on screen, focused first."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                          'ListNames', None, GLib.VariantType('(as)'), Gio.DBusCallFlags.NONE,
                          1000, None).unpack()[0]
    by_pid = {int(name.rsplit('-', 1)[1]): name for name in names
              if name.startswith('org.kde.okular-') and name.rsplit('-', 1)[1].isdigit()}
    pids = visible_pids()
    ordered = [pid for pid in pids if pid in by_pid] if pids is not None else list(by_pid)
    for pid in dict.fromkeys(ordered):
        try:
            path = call(bus, by_pid[pid], 'currentDocument', '(s)')
            current = call(bus, by_pid[pid], 'currentPage', '(u)') - 1  # Okular counts from 1.
        except GLib.Error:
            continue
        if path:
            yield path, current


def find_source(template, deadline=math.inf):
    """Locate a grayscale crop in the PDFs open in Okular; returns a Source or None."""
    for path, current in okular_pages():
        try:
            pdf = document(path)
        except GLib.Error:
            continue
        # Continuous scrolling can leave the selection on a neighboring page.
        found = None
        for index in (current, current + 1, current - 1):
            if time.monotonic() > deadline:
                break
            if 0 <= index < pdf.get_n_pages():
                match = locate(template, pdf.get_page(index))
                if match and (not found or match[0] > found.score):
                    score, scale_x, scale_y, x, y, inverted = match
                    found = Source(path, index, scale_x, scale_y, x, y, inverted, score)
                    if score >= CERTAIN:
                        break
        if found:
            return found
    return None


def render_source(source, width, height, factor):
    """Render the located area at factor times the crop's width and height."""
    page = document(source.path).get_page(source.page)
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, round(width * factor), round(height * factor))
    context = cairo.Context(surface)
    context.set_source_rgb(1, 1, 1)
    context.paint()
    context.save()
    context.scale(source.scale_x * factor, source.scale_y * factor)
    context.translate(-source.x, -source.y)
    page.render(context)
    context.restore()
    if source.inverted:
        context.set_operator(cairo.OPERATOR_DIFFERENCE)
        context.set_source_rgb(1, 1, 1)
        context.paint()
    return surface


def main():
    """Search process for shoot-select: a PNG crop on stdin, a JSON Source or null on stdout.

    shoot-select runs this as a separate process: the search is CPU-heavy
    Python, and in a thread it would hold the interpreter lock and freeze
    the overlay.
    """
    os.nice(10)  # Keep the overlay and the compositor smooth.
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(sys.stdin.buffer.read())
    loader.close()
    source = find_source(gray_pixbuf(loader.get_pixbuf()), time.monotonic() + SEARCH_TIMEOUT)
    print(json.dumps(dataclasses.asdict(source) if source else None))


if __name__ == '__main__':
    main()
