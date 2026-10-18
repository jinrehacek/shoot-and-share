"""Turn a selection, the frozen captures, and annotations into PNG bytes."""
import io

import cairo
import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402

from selection import Box, Rect, Stroke, cover_pixels, crop_plan  # noqa: E402


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


def render(selection, outputs, pixbufs, annotations=()):
    image = crop(selection, outputs, pixbufs)
    if not annotations:
        _, data = image.save_to_bufferv('png', [], [])
        return data
    width, height = image.get_width(), image.get_height()
    scale_x, scale_y = width / selection.w, height / selection.h
    _, data = image.save_to_bufferv('png', ['compression'], ['0'])
    surface = cairo.ImageSurface.create_from_png(io.BytesIO(data))
    context = cairo.Context(surface)
    for annotation in annotations:
        context.set_source_rgb(*annotation.color)
        if isinstance(annotation, Box):
            local = Rect(annotation.rect.x - selection.x, annotation.rect.y - selection.y,
                         annotation.rect.w, annotation.rect.h)
            context.set_antialias(cairo.ANTIALIAS_NONE)
            context.rectangle(*cover_pixels(local, scale_x, scale_y))
            context.fill()
        elif isinstance(annotation, Stroke):
            context.save()
            context.set_antialias(cairo.ANTIALIAS_DEFAULT)
            context.scale(scale_x, scale_y)
            context.translate(-selection.x, -selection.y)
            context.set_line_width(annotation.width)
            context.set_line_cap(cairo.LINE_CAP_ROUND)
            context.set_line_join(cairo.LINE_JOIN_ROUND)
            (x, y), *rest = annotation.points
            context.move_to(x, y)
            for x, y in rest or [(x, y)]:  # A single click still leaves a dot.
                context.line_to(x, y)
            context.stroke()
            context.restore()
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()
