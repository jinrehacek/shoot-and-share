# shoot-select

A region selector for Niri and other wlroots-style compositors. It freezes
every monitor at once, lets you drag a rectangle anywhere, and lets you adjust
it with edge and corner handles before saving. There is no monitor picker, and
a selection can cross monitors.

Niri runs it from the dotfiles bindings:

| Keys | Result |
|------|--------|
| Ctrl+Shift+S | `tablet-share`: Enter saves, copies, and uploads to the tablet gallery |
| Print, Mod+Shift+S | Enter saves to `~/Pictures/Screenshots/` and copies |

Whole-screen (Ctrl+Print) and window (Alt+Print) screenshots stay Niri's own.
Both region bindings share the remembered selection.

## Controls

| Input | Action |
|-------|--------|
| Drag outside the selection | Start a new selection |
| Drag an edge or corner | Resize; dragging past the opposite edge flips it |
| Ctrl while dragging | Resize around the center (new selections and boxes too) |
| Drag inside | Move |
| Arrows / Shift+arrows | Move / resize by 1 px; hold Ctrl for 10 px |
| Ctrl+A | Select the monitor under the pointer |
| Right-click | Clear the selection |
| Enter, Space, double-click inside | Save, copy to clipboard, print `share` |
| Ctrl+C | Copy to clipboard only, print `copy` |
| Escape | Cancel, exit status 1 |

The next run starts with the last saved or copied selection, like Niri's
screenshot UI. It is stored in `~/.local/state/shoot-select/last-selection.json`
and trimmed to the monitors that are connected now.

## Annotations

A toolbar appears under the selection. Annotations land in the saved PNG.

| Tool | Key | Use |
|------|-----|-----|
| Adjust | V | Move and resize the selection (default) |
| Box | R | Drag a solid rectangle; its edges round outward to whole pixels |
| Brush | B | Paint freehand |
| Arrow | A | Drag from tail to tip; Shift snaps to 45° |
| Pick | I | Click to take a color from the screen, then return to the drawing tool |

Q and W make the brush or arrow smaller and bigger; `[` `]` and the scroll wheel
do the same. Keys 1–4 choose black, white, red, or the picked color. Arrows
start red and boxes and brushes black, until you choose a color. Ctrl+Z undoes.
To hide text on a colored background, pick that background and box over the text.

## Sharper from PDFs

The `1×` button at the end of the toolbar (or U) cycles through 1×, 2×, and 4×.
Above 1×, shoot-select looks for the selection in the PDFs open in Okular and
renders that area again from the PDF, so text and vector graphics stay sharp
at two or four times the screen resolution. The size label shows the result,
for example `1800 × 880 · 2× from slides.pdf p. 25`, or says when no PDF matched;
then the capture is saved at 1×.

How it works (`upscale.py`): Okular reports each window's document and current
page over D-Bus. The selection's pixels are matched against the current page and
its neighbors with normalized cross-correlation, first over a range of zoom
levels and then precisely. Okular stretches pages slightly when the screen's
physical DPI differs between axes, so the precise step fits horizontal and
vertical zoom separately. Inverted colors (Okular's dark mode) are matched too,
and the render is inverted to match.

The search runs in a separate low-priority process, started a moment after the
selection stops changing, so the overlay stays responsive; a newer selection
stops an older search. It takes about one second per page, and up to three
pages per Okular window. Enter during a search waits for it, at most 35 seconds.

Limits: only Okular, only a selection within one page, and only what the PDF
itself contains. Paint is applied on top of the sharper image.

## Usage

```bash
shoot-select --output region.png             # Enter saves here and copies
shoot-select --initial 100,100,640,480 ...    # start with this selection instead of the last one
```

Exit status: 0 after Enter or Ctrl+C, 1 after Escape, 2 on errors.

A region on one monitor keeps that monitor's exact pixels. A region across
monitors uses the highest scale among them, and the lower-scale part is scaled
up. Parts outside every monitor are transparent.

## Requirements and install

Python 3 with PyGObject, pycairo, and NumPy, GTK 4.14 or newer, gtk4-layer-shell,
Poppler's GObject bindings, `grim`, and `wl-copy`. On Fedora:
`gtk4-layer-shell grim wl-clipboard python3-gobject python3-numpy poppler-glib`.

```bash
ln -s ~/Projects/ShootAndShare/shoot-select ~/.local/bin/shoot-select
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_selection test_render test_upscale
```

The script re-executes itself with `LD_PRELOAD=libgtk4-layer-shell.so.0`,
which gtk4-layer-shell needs under Python. Its child processes do not inherit
that preload.
