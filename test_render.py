import unittest

import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402

from render import render  # noqa: E402
from selection import Box, Output, Rect, Stroke  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
