"""Turn a selection, the frozen captures, and annotations into PNG bytes."""
import io

import cairo
import gi

gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GdkPixbuf, Pango, PangoCairo  # noqa: E402

from selection import Arrow, Box, Rect, Stroke, Text, cover_pixels, crop_plan  # noqa: E402

TEXT_FONT = 'Sans Bold'
# Measures text for the overlay, which needs bounds before it can draw.
MEASURE = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def text_layout(context, text):
    """The layout for a Text on a cairo context. Unhinted metrics keep the
    overlay, the PNG, and the 2x or 4x PDF render the same width."""
    layout = PangoCairo.create_layout(context)
    options = cairo.FontOptions()
    options.set_hint_metrics(cairo.HINT_METRICS_OFF)
    options.set_hint_style(cairo.HINT_STYLE_NONE)
    PangoCairo.context_set_font_options(layout.get_context(), options)
    layout.context_changed()
    font = Pango.FontDescription.from_string(TEXT_FONT)
    font.set_absolute_size(text.size * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(text.text, -1)
    return layout


def text_origin(layout, text):
    """Top-left of the layout, so the first line is centered on the anchor."""
    _, line = layout.get_line_readonly(0).get_extents()
    return text.anchor[0], text.anchor[1] - line.height / Pango.SCALE / 2


def halo_width(text):
    return max(2, text.size * .16)


def halo_color(color):
    """Black around light text and white around dark text, so it reads on any background."""
    luminance = .2126 * color[0] + .7152 * color[1] + .0722 * color[2]
    return (0, 0, 0) if luminance > .5 else (1, 1, 1)


def paint_text(context, text):
    layout = text_layout(context, text)
    context.move_to(*text_origin(layout, text))
    PangoCairo.layout_path(context, layout)
    context.set_line_join(cairo.LINE_JOIN_ROUND)
    context.set_line_width(halo_width(text))
    context.set_source_rgb(*halo_color(text.color))
    context.stroke_preserve()
    context.set_source_rgb(*text.color)
    context.fill()


def text_bounds(text):
    """(x, y, w, h) a Text covers with its halo, in global logical coordinates."""
    layout = text_layout(MEASURE, text)
    x, y = text_origin(layout, text)
    ink, logical = layout.get_extents()
    left = min(ink.x, logical.x) / Pango.SCALE
    top = min(ink.y, logical.y) / Pango.SCALE
    right = max(ink.x + ink.width, logical.x + logical.width) / Pango.SCALE
    bottom = max(ink.y + ink.height, logical.y + logical.height) / Pango.SCALE
    pad = halo_width(text) / 2 + 2
    return x + left - pad, y + top - pad, right - left + 2 * pad, bottom - top + 2 * pad


def text_caret(text):
    """(x, y, height) of the caret after the last character."""
    layout = text_layout(MEASURE, text)
    x, y = text_origin(layout, text)
    strong, _ = layout.get_cursor_pos(len(text.text.encode()))  # Pango counts UTF-8 bytes.
    return x + strong.x / Pango.SCALE, y + strong.y / Pango.SCALE, strong.height / Pango.SCALE


def crop(selection, outputs, pixbufs):
    width, height, pieces = crop_plan(selection, outputs)
    if len(pieces) == 1 and (pieces[0][1][2:] == pieces[0][2][2:]):
        name, (sx, sy, w, h), _ = pieces[0]
        return pixbufs[name].new_subpixbuf(sx, sy, w, h).copy()
    # Areas outside every monitor stay transparent.
    result = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    result.fill(0)
    for name, (sx, sy, sw, sh), (dx, dy, dw, dh) in pieces:
        scale_x, scale_y = dw / sw, dh / sh
        same = scale_x == 1 and scale_y == 1
        pixbufs[name].scale(result, dx, dy, dw, dh, dx - sx * scale_x, dy - sy * scale_y,
                            scale_x, scale_y,
                            GdkPixbuf.InterpType.NEAREST if same else GdkPixbuf.InterpType.BILINEAR)
    return result


def render(selection, outputs, pixbufs, annotations=(), base=None):
    """PNG bytes of the selection with annotations painted on.

    base is an optional cairo surface that replaces the captured pixels, such
    as the selection rendered again from its PDF; annotations scale to its size.
    """
    if base is None:
        image = crop(selection, outputs, pixbufs)
        if not annotations:
            _, data = image.save_to_bufferv('png', [], [])
            return data
        _, data = image.save_to_bufferv('png', ['compression'], ['0'])
        base = cairo.ImageSurface.create_from_png(io.BytesIO(data))
    surface = base
    width, height = surface.get_width(), surface.get_height()
    scale_x, scale_y = width / selection.w, height / selection.h
    context = cairo.Context(surface)
    for annotation in annotations:
        context.set_source_rgb(*annotation.color)
        if isinstance(annotation, Box):
            local = Rect(annotation.rect.x - selection.x, annotation.rect.y - selection.y,
                         annotation.rect.w, annotation.rect.h)
            context.set_antialias(cairo.ANTIALIAS_NONE)
            context.rectangle(*cover_pixels(local, scale_x, scale_y))
            context.fill()
        elif isinstance(annotation, (Stroke, Arrow)):
            shape = annotation.shape if isinstance(annotation, Arrow) else None
            if isinstance(annotation, Arrow) and not shape:
                continue
            context.save()
            context.set_antialias(cairo.ANTIALIAS_DEFAULT)
            context.scale(scale_x, scale_y)
            context.translate(-selection.x, -selection.y)
            context.set_line_width(annotation.width)
            context.set_line_cap(cairo.LINE_CAP_ROUND)
            context.set_line_join(cairo.LINE_JOIN_ROUND)
            (x, y), *rest = shape[0] if shape else annotation.points
            context.move_to(x, y)
            for x, y in rest or [(x, y)]:  # A single click still leaves a dot.
                context.line_to(x, y)
            context.stroke()
            if shape:
                context.move_to(*shape[1][0])
                for point in shape[1][1:]:
                    context.line_to(*point)
                context.close_path()
                context.fill()
            context.restore()
        elif isinstance(annotation, Text):
            context.save()
            context.set_antialias(cairo.ANTIALIAS_DEFAULT)
            context.scale(scale_x, scale_y)
            context.translate(-selection.x, -selection.y)
            paint_text(context, annotation)
            context.restore()
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()
