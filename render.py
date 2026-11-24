"""Turn a selection, the frozen captures, and annotations into PNG bytes."""
import io

import cairo
import gi
import numpy as np

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402

from selection import Arrow, Box, Outline, Rect, Stroke, cover_pixels, crop_plan  # noqa: E402


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


def remove_white_background(surface):
    """Copy to ARGB32 and clear exact white pixels, preserving all other pixels."""
    result = cairo.ImageSurface(cairo.FORMAT_ARGB32, surface.get_width(), surface.get_height())
    context = cairo.Context(result)
    context.set_source_surface(surface)
    context.paint()
    result.flush()
    # Cairo's native-endian ARGB32 is a premultiplied 0xAARRGGBB word.
    pixels = np.ndarray((result.get_height(), result.get_width()), dtype=np.uint32,
                        buffer=result.get_data(), strides=(result.get_stride(), 4))
    alpha = pixels >> 24
    white = (alpha > 0) & ((pixels & 0xffffff) == alpha * 0x010101)
    pixels[white] = 0
    result.mark_dirty()
    return result


def render(selection, outputs, pixbufs, annotations=(), base=None, remove_white=False):
    """PNG bytes of the selection with annotations painted on.

    base is an optional cairo surface that replaces the captured pixels, such
    as the selection rendered again from its PDF; annotations scale to its size.
    remove_white clears exact white pixels after painting annotations.
    """
    if base is None:
        image = crop(selection, outputs, pixbufs)
        if not annotations and not remove_white:
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
        elif isinstance(annotation, Outline):
            context.save()
            context.set_antialias(cairo.ANTIALIAS_DEFAULT)
            context.scale(scale_x, scale_y)
            context.translate(-selection.x, -selection.y)
            context.set_line_width(annotation.width)
            context.set_line_join(cairo.LINE_JOIN_MITER)
            path = annotation.path
            context.rectangle(path.x, path.y, path.w, path.h)
            context.stroke()
            context.restore()
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
    if remove_white:
        surface = remove_white_background(surface)
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()
