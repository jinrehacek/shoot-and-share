"""Selection geometry for shoot-select, kept free of GTK so it can be tested.

All rectangles use the compositor's global logical coordinates, the same space
Niri reports output positions in. Pixels only appear in crop_plan, where each
output's own scale converts logical edges to that output's captured pixels.
"""
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


def drag(zone, start, dx, dy, bounds):
    """Move or resize the selection that existed when the drag began."""
    if zone == 'move':
        return Rect(clamp(round(start.x + dx), bounds.x, bounds.right - start.w),
                    clamp(round(start.y + dy), bounds.y, bounds.bottom - start.h),
                    start.w, start.h)
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


def nudge(rect, dx, dy, resize, bounds):
    """Keyboard adjustment: move the selection, or with resize move its right and bottom edges."""
    if resize:
        return Rect(rect.x, rect.y,
                    clamp(rect.w + dx, 1, bounds.right - rect.x),
                    clamp(rect.h + dy, 1, bounds.bottom - rect.y))
    return drag('move', rect, dx, dy, bounds)


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
