"""Selection geometry and annotations for shoot-select, kept free of GTK so it can be tested.

All rectangles use the compositor's global logical coordinates, the same space
Niri reports output positions in. Pixels only appear in crop_plan, where each
output's own scale converts logical edges to that output's captured pixels.
"""
import math
from dataclasses import dataclass

HANDLE_GRAB = 12  # Logical pixels around an edge or corner that grab it.
MIN_NEW_SIZE = 3  # A smaller drag counts as a click and keeps the old selection.


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @classmethod
    def span(cls, x0, y0, x1, y1):
        """Rectangle between two points in any order, so edges can cross over."""
        return cls(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    def contains(self, x, y):
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def intersect(self, other):
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        x1, y1 = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None

    def union(self, other):
        return Rect.span(min(self.x, other.x), min(self.y, other.y),
                         max(self.right, other.right), max(self.bottom, other.bottom))


@dataclass(frozen=True)
class Output:
    name: str
    rect: Rect  # Logical geometry.
    pixel_w: int  # Captured image size.
    pixel_h: int

    @property
    def scale(self):
        return self.pixel_w / self.rect.w


def clamp(value, low, high):
    return max(low, min(high, value))


def hit_test(rect, x, y, grab=HANDLE_GRAB):
    """Return the part of the selection under a point.

    Edges and corners are 'n', 'se', and so on; 'move' is the inside; None is
    outside, where a drag starts a new selection.
    """
    if rect is None:
        return None
    # Keep the middle of small selections movable.
    grab = min(grab, max(3, min(rect.w, rect.h) / 3))
    if not (rect.x - grab <= x <= rect.right + grab and rect.y - grab <= y <= rect.bottom + grab):
        return None
    left, right = abs(x - rect.x), abs(x - rect.right)
    top, bottom = abs(y - rect.y), abs(y - rect.bottom)
    vertical = 'n' if top <= grab and top <= bottom else 's' if bottom <= grab else ''
    horizontal = 'w' if left <= grab and left <= right else 'e' if right <= grab else ''
    if vertical or horizontal:
        return vertical + horizontal
    return 'move' if rect.contains(x, y) else None


def drag(zone, start, dx, dy, bounds, centered=False):
    """Move or resize the selection that existed when the drag began.

    With centered, the opposite edge mirrors the dragged one, so the
    rectangle grows or shrinks around its center.
    """
    if zone == 'move':
        return Rect(clamp(round(start.x + dx), bounds.x, bounds.right - start.w),
                    clamp(round(start.y + dy), bounds.y, bounds.bottom - start.h),
                    start.w, start.h)
    if centered:
        center_x, center_y = start.x + start.w / 2, start.y + start.h / 2
        half_w, half_h = start.w / 2, start.h / 2
        if 'w' in zone:
            half_w = abs(start.x + dx - center_x)
        if 'e' in zone:
            half_w = abs(start.right + dx - center_x)
        if 'n' in zone:
            half_h = abs(start.y + dy - center_y)
        if 's' in zone:
            half_h = abs(start.bottom + dy - center_y)
        return centered_span(center_x, center_y, half_w, half_h, bounds)
    x0, y0, x1, y1 = start.x, start.y, start.right, start.bottom
    if 'w' in zone:
        x0 += dx
    if 'e' in zone:
        x1 += dx
    if 'n' in zone:
        y0 += dy
    if 's' in zone:
        y1 += dy
    return span_within(x0, y0, x1, y1, bounds)


def span_within(x0, y0, x1, y1, bounds):
    """Whole-pixel rectangle between two points, kept inside the desktop."""
    def x(value):
        return clamp(round(value), bounds.x, bounds.right)

    def y(value):
        return clamp(round(value), bounds.y, bounds.bottom)
    return Rect.span(x(x0), y(y0), x(x1), y(y1))


def centered_span(center_x, center_y, half_w, half_h, bounds):
    """Rectangle around a center, shrunk evenly so both sides stay on the desktop."""
    half_w = min(half_w, center_x - bounds.x, bounds.right - center_x)
    half_h = min(half_h, center_y - bounds.y, bounds.bottom - center_y)
    return span_within(center_x - half_w, center_y - half_h,
                       center_x + half_w, center_y + half_h, bounds)


def nudge(rect, dx, dy, resize, bounds):
    """Keyboard adjustment: move the selection, or with resize move its right and bottom edges."""
    if resize:
        return Rect(rect.x, rect.y,
                    clamp(rect.w + dx, 1, bounds.right - rect.x),
                    clamp(rect.h + dy, 1, bounds.bottom - rect.y))
    return drag('move', rect, dx, dy, bounds)


def restore(rect, outputs):
    """A remembered selection fitted to the current outputs, or None if it no longer fits.

    Monitors may have been unplugged or rearranged since it was saved; a
    selection that no longer touches any output is dropped.
    """
    if rect is None or rect.w < 1 or rect.h < 1:
        return None
    bounds = outputs[0].rect
    for output in outputs[1:]:
        bounds = bounds.union(output.rect)
    fitted = bounds.intersect(rect)
    if not fitted or not any(fitted.intersect(output.rect) for output in outputs):
        return None
    return fitted


def crop_plan(selection, outputs):
    """Plan the PNG for a selection that may cover several outputs.

    Returns (width, height, pieces). Each piece copies a source pixel rectangle
    from one output's capture to a destination rectangle in the result. The
    result uses the highest scale among the covered outputs, so an area on one
    monitor keeps that monitor's exact pixels.
    """
    covered = [(output, part) for output in outputs
               if (part := selection.intersect(output.rect))]
    if not covered:
        return 0, 0, []
    scale = max(output.scale for output, _ in covered)
    width, height = round(selection.w * scale), round(selection.h * scale)
    pieces = []
    for output, part in covered:
        sx0 = round((part.x - output.rect.x) * output.scale)
        sy0 = round((part.y - output.rect.y) * output.scale)
        sx1 = round((part.right - output.rect.x) * output.scale)
        sy1 = round((part.bottom - output.rect.y) * output.scale)
        dx0, dy0 = round((part.x - selection.x) * scale), round((part.y - selection.y) * scale)
        dx1, dy1 = round((part.right - selection.x) * scale), round((part.bottom - selection.y) * scale)
        if sx1 > sx0 and sy1 > sy0 and dx1 > dx0 and dy1 > dy0:
            pieces.append((output.name, (sx0, sy0, sx1 - sx0, sy1 - sy0),
                           (dx0, dy0, dx1 - dx0, dy1 - dy0)))
    return width, height, pieces


@dataclass(frozen=True)
class Box:
    """A filled rectangle that hides what is under it."""
    rect: Rect
    color: tuple  # (red, green, blue), each 0 to 1.


@dataclass(frozen=True)
class Outline:
    """A hollow rectangle whose border sits outside rect, so it never covers what it frames."""
    rect: Rect
    width: float
    color: tuple

    @property
    def path(self):
        """The rectangle to stroke with width and mitered corners, shared by the overlay and PNG renderer."""
        half = self.width / 2
        return Rect(self.rect.x - half, self.rect.y - half, self.rect.w + self.width, self.rect.h + self.width)


@dataclass(frozen=True)
class Stroke:
    """A freehand brush stroke through global logical points."""
    points: tuple
    width: float
    color: tuple


@dataclass(frozen=True)
class Arrow:
    """A straight arrow from tail to tip in global logical coordinates."""
    start: tuple
    end: tuple
    width: float
    color: tuple

    @property
    def shape(self):
        """Shaft and filled head, shared by the overlay and PNG renderer."""
        return arrow_shape(self.start, self.end, self.width)


def arrow_shape(start, end, width, head=None):
    """The shaft as (tail, head base) and the head as a triangle, or () for a click.
    The head grows with the line so thick arrows stay readable, but never takes
    more than most of a short arrow."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < MIN_NEW_SIZE:
        return ()
    ux, uy = dx / length, dy / length
    head = min(head or max(14, width * 4), length * .6)
    wing = max(head * .5, width)  # The base stays wider than the shaft.
    x, y = end[0] - ux * head, end[1] - uy * head
    return ((start, (x, y)), ((x - uy * wing, y + ux * wing), end, (x + uy * wing, y - ux * wing)))


def snap_angle(dx, dy):
    """An offset turned to the nearest multiple of 45 degrees, keeping its length."""
    length = math.hypot(dx, dy)
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
    return round(length * math.cos(angle), 6), round(length * math.sin(angle), 6)


def cover_pixels(rect, scale_x, scale_y):
    """Whole result pixels a box covers, rounded outward so no partly covered
    pixel lets the hidden content show through. rect is relative to the selection."""
    x0, y0 = math.floor(rect.x * scale_x + 1e-6), math.floor(rect.y * scale_y + 1e-6)
    x1, y1 = math.ceil(rect.right * scale_x - 1e-6), math.ceil(rect.bottom * scale_y - 1e-6)
    return x0, y0, x1 - x0, y1 - y0


def place_toolbar(selection, outputs, width, height, gap=10):
    """Put the toolbar under the selection, on the output showing its bottom.

    It moves inside the selection's bottom edge when the output has no room
    below, and stays within that output horizontally.
    """
    anchor_x, anchor_y = selection.x + selection.w / 2, selection.bottom
    rects = [output.rect for output in outputs]
    area = next((r for r in rects if r.contains(anchor_x, anchor_y)), None)
    area = area or next((r for r in rects if r.intersect(selection)), rects[0])
    y = selection.bottom + gap
    if y + height > area.bottom:
        y = max(selection.y, selection.bottom - gap - height)
    y = clamp(y, area.y, area.bottom - height)
    x = clamp(selection.x, area.x, area.right - width)
    return Rect(x, y, width, height)
