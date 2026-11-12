import unittest

import cairo
import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402

from render import render  # noqa: E402
from selection import Arrow, Box, Output, Rect, Stroke  # noqa: E402

GRAY = (128, 128, 128)


def solid(width, height, color):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
    pixbuf.fill(color[0] << 24 | color[1] << 16 | color[2] << 8 | 0xff)
    return pixbuf


def decode(data):
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(data)
    loader.close()
    image = loader.get_pixbuf()
    pixels, stride, channels = image.get_pixels(), image.get_rowstride(), image.get_n_channels()
    return image, lambda x, y: tuple(pixels[y * stride + x * channels:][:3])


class Render(unittest.TestCase):
    laptop = Output('eDP-1', Rect(0, 0, 100, 100), 100, 100)
    monitor = Output('HDMI-A-1', Rect(100, 0, 80, 80), 100, 100)  # Scale 1.25.
    pixbufs = {'eDP-1': solid(100, 100, GRAY), 'HDMI-A-1': solid(100, 100, (0, 0, 200))}

    def test_box_covers_whole_pixels_at_fractional_scale(self):
        selection = Rect(110, 10, 40, 40)
        image, pixel = decode(render(selection, [self.laptop, self.monitor], self.pixbufs,
                                     [Box(Rect(111, 11, 2, 2), (1, 1, 1))]))
        self.assertEqual((image.get_width(), image.get_height()), (50, 50))
        # Logical 1..3 maps to pixels 1.25..3.75, so pixels 1, 2, and 3 must be white.
        self.assertEqual([pixel(x, 2) for x in range(6)],
                         [(0, 0, 200), (255, 255, 255), (255, 255, 255), (255, 255, 255),
                          (0, 0, 200), (0, 0, 200)])

    def test_stroke_paints_in_selection_coordinates(self):
        _, pixel = decode(render(Rect(10, 10, 50, 50), [self.laptop], self.pixbufs,
                                 [Stroke(((20, 30), (40, 30)), 6, (0, 0, 0))]))
        self.assertEqual(pixel(20, 20), (0, 0, 0))
        self.assertEqual(pixel(20, 30), GRAY)

    def test_without_annotations_pixels_are_untouched(self):
        image, pixel = decode(render(Rect(90, 0, 20, 10), [self.laptop, self.monitor], self.pixbufs))
        self.assertEqual(image.get_width(), 25)
        self.assertEqual(pixel(5, 5), GRAY)
        self.assertEqual(pixel(20, 5), (0, 0, 200))

    def test_arrow_shaft_and_head_in_every_direction(self):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
            with self.subTest(direction=(dx, dy)):
                end = (50 + dx * 30, 50 + dy * 30)
                _, pixel = decode(render(Rect(0, 0, 100, 100), [self.laptop], self.pixbufs,
                                         [Arrow((50, 50), end, 4, (0, 0, 0))]))
                self.assertEqual(pixel(50 + dx * 15, 50 + dy * 15), (0, 0, 0))
                # The head must have painted pixels off the shaft near the tip.
                self.assertTrue(any(pixel(x, y) == (0, 0, 0)
                                    for x in range(end[0] - 14, end[0] + 15)
                                    for y in range(end[1] - 14, end[1] + 15)
                                    if abs((x - 50) * dy - (y - 50) * dx) >= 4))

    def test_arrow_scales_and_translates_on_pdf_base(self):
        base = cairo.ImageSurface(cairo.FORMAT_RGB24, 200, 100)
        _, pixel = decode(render(Rect(100, 200, 100, 50), [], {},
                                 [Arrow((110, 225), (180, 225), 4, (1, 1, 1))], base))
        self.assertEqual(pixel(80, 50), (255, 255, 255))
        # Logical (168.25, 228.25): inside the head, 3.25 off the axis, past the shaft's 2.
        self.assertEqual(pixel(136, 56), (255, 255, 255))
        self.assertEqual(pixel(80, 60), (0, 0, 0))

    def test_tiny_arrow_leaves_pixels_untouched(self):
        _, pixel = decode(render(Rect(0, 0, 100, 100), [self.laptop], self.pixbufs,
                                 [Arrow((50, 50), (51, 51), 4, (0, 0, 0))]))
        self.assertEqual(pixel(50, 50), GRAY)

    def test_white_removal_is_optional_and_exact(self):
        output = Output('test', Rect(0, 0, 3, 2), 3, 2)
        # Three RGB pixels leave padding at the end of each source row.
        pixbuf = solid(3, 2, (255, 255, 255))
        pixbufs = {'test': pixbuf}
        annotations = [Box(Rect(1, 0, 1, 2), (254 / 255, 1, 1)),
                       Box(Rect(2, 0, 1, 2), (1, 0, 0))]
        original, _ = decode(render(output.rect, [output], pixbufs, annotations))
        self.assertFalse(original.get_has_alpha())
        image, pixel = decode(render(output.rect, [output], pixbufs, annotations,
                                     remove_white=True))
        for y in range(2):
            self.assertEqual(self.alpha(image, 0, y), 0)
            self.assertEqual(self.alpha(image, 1, y), 255)
            self.assertEqual(self.alpha(image, 2, y), 255)
            self.assertEqual(pixel(1, y), (254, 255, 255))
            self.assertEqual(pixel(2, y), (255, 0, 0))
        # Exporting with removal must leave the frozen capture intact.
        self.assertEqual(pixbuf.get_pixels()[:3], b'\xff\xff\xff')

    def test_white_capture_without_annotations_becomes_transparent(self):
        image, _ = decode(render(Rect(0, 0, 100, 100), [self.laptop],
                                 {'eDP-1': solid(100, 100, (255, 255, 255))},
                                 remove_white=True))
        self.assertEqual(self.alpha(image, 50, 50), 0)

    def test_white_removal_on_pdf_base_preserves_existing_alpha(self):
        base = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 4)
        context = cairo.Context(base)
        context.set_source_rgb(1, 1, 1)
        context.rectangle(0, 0, 2, 4)
        context.fill()
        context.set_source_rgba(1, 0, 0, .5)
        context.rectangle(2, 0, 2, 4)
        context.fill()
        image, pixel = decode(render(Rect(0, 0, 4, 2), [], {}, base=base,
                                     remove_white=True))
        self.assertEqual((image.get_width(), image.get_height()), (8, 4))
        self.assertEqual(self.alpha(image, 0, 0), 0)
        self.assertEqual(self.alpha(image, 2, 0), 128)
        self.assertEqual(pixel(2, 0), (255, 0, 0))
        self.assertEqual(self.alpha(image, 7, 0), 0)
        # Toggling back off can reuse the original PDF surface.
        original, _ = decode(render(Rect(0, 0, 4, 2), [], {}, base=base))
        self.assertEqual(self.alpha(original, 0, 0), 255)

    def test_white_annotations_and_rgb_pdf_background_become_transparent(self):
        base = cairo.ImageSurface(cairo.FORMAT_RGB24, 100, 100)
        image, pixel = decode(render(Rect(0, 0, 50, 50), [], {},
                                     [Box(Rect(10, 10, 10, 10), (1, 1, 1))], base,
                                     remove_white=True))
        self.assertEqual(self.alpha(image, 25, 25), 0)
        self.assertEqual(self.alpha(image, 0, 0), 255)
        self.assertEqual(pixel(0, 0), (0, 0, 0))

    @staticmethod
    def alpha(image, x, y):
        return image.get_pixels()[y * image.get_rowstride() + x * 4 + 3]


if __name__ == '__main__':
    unittest.main()
