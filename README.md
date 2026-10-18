# shoot-select

A region selector for Niri and other wlroots-style compositors. It freezes
every monitor at once, lets you drag a rectangle anywhere, and lets you adjust
it with edge and corner handles before saving. There is no monitor picker, and
a selection can cross monitors.

`tablet-share` from the dotfiles runs it for **Ctrl+Shift+S**.

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

## Hiding things

A toolbar appears under the selection. Paint lands in the saved PNG.

| Tool | Key | Use |
|------|-----|-----|
| Adjust | V | Move and resize the selection (default) |
| Box | R | Drag a solid rectangle; its edges round outward to whole pixels |
| Brush | B | Paint freehand; `[` `]` or the scroll wheel change the size |
| Pick | I | Click to take a color from the screen, then return to Box or Brush |

Keys 1–4 choose black, white, red, or the picked color. Ctrl+Z undoes.
To hide text on a colored background, pick that background and box over the text.

## Usage

```bash
shoot-select --output region.png             # Enter saves here and copies
shoot-select --initial 100,100,640,480 ...    # start with a selection (logical coordinates)
```

Exit status: 0 after Enter or Ctrl+C, 1 after Escape, 2 on errors.

A region on one monitor keeps that monitor's exact pixels. A region across
monitors uses the highest scale among them, and the lower-scale part is scaled
up. Parts outside every monitor are transparent.

## Requirements and install

Python 3 with PyGObject and pycairo, GTK 4.14 or newer, gtk4-layer-shell,
`grim`, and `wl-copy`. On Fedora: `gtk4-layer-shell grim wl-clipboard python3-gobject`.

```bash
ln -s ~/Projects/ShootAndShare/shoot-select ~/.local/bin/shoot-select
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_selection test_render
```

The script re-executes itself with `LD_PRELOAD=libgtk4-layer-shell.so.0`,
which gtk4-layer-shell needs under Python. Its child processes do not inherit
that preload.
