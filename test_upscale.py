import math
import tempfile
import unittest
from pathlib import Path

import cairo

import upscale


def make_pdf(path):
    """A two-page PDF with text and shapes, so matches have something to find."""
    surface = cairo.PDFSurface(str(path), 600, 400)
    context = cairo.Context(surface)
    for page in range(2):
        context.set_source_rgb(1, 1, 1)
        context.paint()
        context.set_source_rgb(0, 0, 0)
        context.select_font_face('Sans')
        context.set_font_size(18)
        words = ('the quick brown fox', 'jumps over a lazy dog')[page]
        for line in range(8 - 3 * page):
            context.move_to(40 + 30 * page, 60 + line * (36 + 20 * page))
            context.show_text(f'Page {page} line {line}: {words} {line * 7 + page}')
        context.set_line_width(3)
        context.arc(480 - 300 * page, 300, 40 + page * 15, 0, 2 * math.pi)
        context.stroke()
        context.rectangle(400 - page * 200, 40 + page * 250, 120, 70)
        context.fill()
        context.show_page()
    surface.finish()


def screen(page, scale_x, scale_y):
    """The page as a viewer with non-square zoom and a sub-pixel offset would show it."""
    width, height = page.get_size()
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, round(width * scale_x) + 2, round(height * scale_y) + 2)
    context = cairo.Context(surface)
    context.set_source_rgb(1, 1, 1)
    context.paint()
    context.translate(.4, .3)
    context.scale(scale_x, scale_y)
    page.render(context)
    return upscale.gray(surface)


class Locate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name) / 'test.pdf'
        make_pdf(cls.path)
        cls.pdf = upscale.document(str(cls.path))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_finds_a_stretched_view(self):
        page = self.pdf.get_page(0)
        crop = screen(page, 1.8, 1.73)[100:500, 200:900]
        score, scale_x, scale_y, x, y, inverted = upscale.locate(crop, page)
        self.assertGreater(score, upscale.MATCH_THRESHOLD)
        self.assertAlmostEqual(scale_x, 1.8, delta=.02)
        self.assertAlmostEqual(scale_y, 1.73, delta=.02)
        # Within two screen pixels of the true corner.
        self.assertAlmostEqual(x * 1.8, 200.4, delta=2)
        self.assertAlmostEqual(y * 1.73, 100.3, delta=2)
        self.assertFalse(inverted)

    def test_finds_inverted_colors(self):
        page = self.pdf.get_page(1)
        crop = 255 - screen(page, 2.5, 2.5)[300:700, 100:800]
        self.assertTrue(upscale.locate(crop, page)[5])

    def test_rejects_a_different_page(self):
        crop = screen(self.pdf.get_page(0), 1.8, 1.8)[100:500, 200:900]
        self.assertIsNone(upscale.locate(crop, self.pdf.get_page(1)))

    def test_rejects_a_blank_area(self):
        self.assertIsNone(upscale.locate(screen(self.pdf.get_page(0), 2, 2)[700:780, 10:200], self.pdf.get_page(0)))

    def test_render_source_size(self):
        source = upscale.Source(str(self.path), 0, 1.8, 1.73, 100, 50, False, 1)
        surface = upscale.render_source(source, 700, 400, 2)
        self.assertEqual((surface.get_width(), surface.get_height()), (1400, 800))


if __name__ == '__main__':
    unittest.main()
