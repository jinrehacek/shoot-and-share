import unittest

from selection import Output, Rect, crop_plan, drag, hit_test, nudge, span_within

# The laptop layout: a 1x laptop panel and a 1.25x monitor to its right.
LAPTOP = Output('eDP-1', Rect(0, 0, 1920, 1200), 1920, 1200)
MONITOR = Output('HDMI-A-1', Rect(1920, 0, 1536, 960), 1920, 1200)
BOUNDS = Rect(0, 0, 3456, 1200)


class HitTest(unittest.TestCase):
    selection = Rect(100, 100, 200, 100)

    def test_corners_edges_inside_and_outside(self):
        self.assertEqual(hit_test(self.selection, 100, 100), 'nw')
        self.assertEqual(hit_test(self.selection, 305, 205), 'se')
        self.assertEqual(hit_test(self.selection, 200, 95), 'n')
        self.assertEqual(hit_test(self.selection, 302, 150), 'e')
        self.assertEqual(hit_test(self.selection, 200, 150), 'move')
        self.assertIsNone(hit_test(self.selection, 50, 50))
        self.assertIsNone(hit_test(None, 200, 150))

    def test_small_selection_stays_movable(self):
        small = Rect(100, 100, 12, 12)
        self.assertEqual(hit_test(small, 106, 106), 'move')
        self.assertEqual(hit_test(small, 112, 112), 'se')


class Drag(unittest.TestCase):
    start = Rect(100, 100, 200, 100)

    def test_resize_one_edge(self):
        self.assertEqual(drag('e', self.start, 50, 30, BOUNDS), Rect(100, 100, 250, 100))
        self.assertEqual(drag('n', self.start, 50, -30, BOUNDS), Rect(100, 70, 200, 130))

    def test_resize_past_the_opposite_edge_flips(self):
        self.assertEqual(drag('w', self.start, 250, 0, BOUNDS), Rect(300, 100, 50, 100))

    def test_move_stays_on_the_desktop(self):
        self.assertEqual(drag('move', self.start, -500, 5000, BOUNDS), Rect(0, 1100, 200, 100))

    def test_new_selection_crosses_monitors(self):
        self.assertEqual(span_within(1800, 50, 2000.4, -40, BOUNDS), Rect(1800, 0, 200, 50))

    def test_keyboard_resize(self):
        self.assertEqual(nudge(self.start, -10, 1, True, BOUNDS), Rect(100, 100, 190, 101))
        self.assertEqual(nudge(self.start, -10, 1, False, BOUNDS), Rect(90, 101, 200, 100))


class CropPlan(unittest.TestCase):
    def test_one_output_keeps_native_pixels(self):
        self.assertEqual(crop_plan(Rect(10, 20, 30, 40), [LAPTOP, MONITOR]),
                         (30, 40, [('eDP-1', (10, 20, 30, 40), (10 - 10, 0, 30, 40))]))

    def test_scaled_output_uses_its_pixels(self):
        width, height, pieces = crop_plan(Rect(1920 + 100, 100, 400, 200), [LAPTOP, MONITOR])
        self.assertEqual((width, height), (500, 250))
        self.assertEqual(pieces, [('HDMI-A-1', (125, 125, 500, 250), (0, 0, 500, 250))])

    def test_span_uses_the_highest_scale(self):
        width, height, pieces = crop_plan(Rect(1820, 0, 200, 100), [LAPTOP, MONITOR])
        self.assertEqual((width, height), (250, 125))
        self.assertEqual(pieces, [('eDP-1', (1820, 0, 100, 100), (0, 0, 125, 125)),
                                  ('HDMI-A-1', (0, 0, 125, 125), (125, 0, 125, 125))])

    def test_area_outside_every_output(self):
        self.assertEqual(crop_plan(Rect(2000, 1000, 50, 50), [LAPTOP, MONITOR]), (0, 0, []))


if __name__ == '__main__':
    unittest.main()
