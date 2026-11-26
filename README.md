# shoot-and-share

Region screenshots for Niri, in two parts:

- `shoot-select` freezes every monitor at once. You drag a rectangle anywhere,
  even across monitors, adjust it with handles, draw arrows or boxes on it, and
  press Enter. The PNG is saved and copied to the clipboard.
- `share/` is optional. It sends that PNG over SSH to a server of yours, which
  keeps a small web gallery you can open on a tablet or phone.

It is built and used on Niri. It should run on any compositor with
wlr-layer-shell and wlr-screencopy, such as Sway or Hyprland, but I haven't
tried those.

## Install

You need Python 3 with PyGObject, pycairo, and NumPy, GTK 4.14 or newer,
gtk4-layer-shell, Poppler's GObject bindings, `grim`, and `wl-copy`.

```bash
# Fedora
sudo dnf install gtk4-layer-shell grim wl-clipboard python3-gobject python3-numpy poppler-glib
# Debian 13
sudo apt install python3-gi python3-gi-cairo python3-numpy gir1.2-gtk-4.0 gir1.2-poppler-0.18 \
    gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 grim wl-clipboard
```

Then clone the repository and link the script onto your `PATH`:

```bash
git clone https://github.com/jinrehacek/shoot-and-share.git
cd shoot-and-share
ln -s "$PWD/shoot-select" ~/.local/bin/shoot-select
```

Bind it to a key. For Niri, in `~/.config/niri/config.kdl`:

```kdl
binds {
    Print repeat=false { spawn-sh "~/.local/bin/shoot-select --output ~/Pictures/Screenshots/\"Screenshot from $(date '+%Y-%m-%d %H-%M-%S').png\""; }
    // Only after setting up the gallery below:
    Ctrl+Shift+S repeat=false { spawn-sh "~/.local/bin/tablet-share"; }
}
```

The script re-executes itself with `LD_PRELOAD=libgtk4-layer-shell.so.0`,
which gtk4-layer-shell needs under Python. Its child processes do not inherit
that preload.

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
| T | Toggle pure white background removal |
| Escape | Cancel, exit status 1 |

The next run starts with the last saved or copied selection, like Niri's
screenshot UI. It is stored in `~/.local/state/shoot-select/last-selection.json`
and trimmed to the monitors that are connected now.

## Annotations

A toolbar appears under the selection. Annotations land in the saved PNG.

| Tool | Key | Use |
|------|-----|-----|
| Adjust | V | Move and resize the selection (default) |
| Arrow | A | Drag from tail to tip; Shift snaps to 45° |
| Outline | S | Drag a hollow rectangle; the border sits outside what you dragged around |
| Draw | D | Paint freehand |
| Fill | F | Drag a solid rectangle; its edges round outward to whole pixels |
| Eyedropper | E | Click to take a color from the screen, then return to the drawing tool |

Every key sits under the left hand, so the right one can stay on the mouse.

Q and W make the outline, brush, or arrow thinner and thicker; `[` `]` and the
scroll wheel do the same. Keys 1–4 choose black, white, red, or the picked color.
Arrows and outlines start red and boxes and brushes black, until you choose a
color. Z or Ctrl+Z undoes.
To hide text on a colored background, take that background with E and fill over the text with F.

## Sharper from PDFs

The `1×` button at the end of the toolbar (or X) cycles through 1×, 2×, and 4×.
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
On Niri, only Okular windows on visible workspaces are searched, the focused
one first; elsewhere every open Okular window is.

Limits: only Okular, only a selection within one page, and only what the PDF
itself contains. Paint is applied on top of the sharper image.

## Transparent background

Press T or click the eraser button after `1×` to toggle white background
removal. It starts off each run. When enabled, every pure white pixel becomes
transparent in the saved and copied PNG, including white annotations. Off-white
pixels and other colors stay unchanged. This works with captures from any app
and with the sharper PDF render from Okular. The selection label confirms when
removal is enabled; the overlay still shows the original background.

## Command line

```bash
shoot-select --output region.png             # Enter saves here and copies
shoot-select --initial 100,100,640,480 ...    # start with this selection instead of the last one
```

Without `--output`, Enter only copies. After Enter it prints `share`, after
Ctrl+C `copy`. Exit status: 0 after Enter or Ctrl+C, 1 after Escape, 2 on errors.
That is enough to script around it; `share/tablet-share` is one such script.

A region on one monitor keeps that monitor's exact pixels. A region across
monitors uses the highest scale among them, and the lower-scale part is scaled
up. Parts outside every monitor are transparent.

## Share to a gallery

I wanted screenshots from the laptop on my tablet. With the gallery set up, a second key runs `tablet-share`: you select a region as usual,
Enter uploads it, and a page on your server shows it a few seconds later.

```text
tablet-share runs shoot-select
  → the PNG goes to your server over SSH (no upload API on the web)
  → tablet-share-server checks the PNG and its SHA-256, stores it, rebuilds the page
  → any static web server publishes the folder
  → the laptop downloads the published PNG and compares the checksum
```

The page shows the last seven days, newest first, and checks for new images
every five seconds. Click an image to open the PNG; hold or drag it to copy it.
Older images move to an archive page.

The server side is one Python file with no dependencies beyond Python 3. It
writes files atomically under a lock, so retries and two uploads at once are
safe, and the same image sent twice is stored once.

> [!WARNING]
> The gallery has no login. Anyone who can reach its address sees every
> screenshot from the last 30 days. Keep it on a private network (Tailscale,
> WireGuard, your LAN) or behind a reverse proxy that asks for a password.
> Both ways of serving it below listen only on 127.0.0.1 unless you change that.

### 1. Install the receiver on the server

You need SSH access to the server without a password prompt (a key), and Python 3
there. From the repository on your laptop:

```bash
share/install-server myserver tablet-share/gallery
```

`myserver` is anything `ssh` accepts. The gallery folder is relative to your
home directory on the server. The installer puts `tablet-share-server` in
`~/.local/bin`, builds an empty gallery, and enables a daily cleanup timer as a
systemd user unit. Run it again after pulling changes; it keeps the images.

### 2. Publish the folder

Pick one.

**Docker.** Copy `share/docker/` to the server and start it:

```bash
GALLERY_DIR=$HOME/tablet-share/gallery docker compose up -d
```

It runs Caddy with the folder mounted read-only, on `127.0.0.1:8080`.
`GALLERY_BIND` and `GALLERY_PORT` change the address and port.

**Without Docker.** The installer also put a small web server on the server:

```bash
ssh myserver 'sudo loginctl enable-linger $USER'   # keep it running after you log out
ssh myserver systemctl --user enable --now tablet-share-web
```

Without lingering, systemd stops it as soon as your last SSH session closes.
It also listens on `127.0.0.1:8080`. `systemctl --user edit tablet-share-web`
changes that; the unit file shows how.

**A web server you already run.** Point it at the gallery folder and turn off
directory listings.

### 3. Reach it from the tablet

Pick whatever network you already have.

- **Tailscale.** On the server, `sudo tailscale serve --bg 8080`. The gallery is
  at `https://myserver.your-tailnet.ts.net/`, with HTTPS, only on your tailnet.
  If something already uses that address, add `--https=8443` and append
  `:8443` to the URL.
- **WireGuard or LAN.** Listen on the server's address in that network instead
  of 127.0.0.1, for example `GALLERY_BIND=10.0.0.1` for Docker or
  `--bind 10.0.0.1` for `tablet-share-web`. The gallery is at
  `http://10.0.0.1:8080/`. Check that your firewall doesn't open that port to
  the internet.
- **Public internet.** Put a reverse proxy with a password in front, such as
  Caddy with `basic_auth`. Don't publish the port directly.

### 4. Set up the laptop

```bash
ln -s "$PWD/share/tablet-share" ~/.local/bin/tablet-share
mkdir -p ~/.config/tablet-share
cat > ~/.config/tablet-share/config <<'EOF'
TABLET_SHARE_HOST=myserver
TABLET_SHARE_URL=https://myserver.your-tailnet.ts.net/
EOF
```

`TABLET_SHARE_URL` is the address from step 3, as the laptop sees it. The
laptop must reach it too, since it checks every upload there. Environment
variables with the same names override the file.

Bind `tablet-share` to a key (see [Install](#install)). Enter shares; Ctrl+C
only copies, and Escape uploads nothing.

If the upload fails, the PNG stays in `~/Pictures/tablet-drop/` and a pending
record in `~/.local/state/tablet-share/`. To retry every two minutes:

```bash
cp share/systemd/tablet-share-retry.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tablet-share-retry.timer
```

Other commands:

```bash
tablet-share --retry                        # send pending uploads now
tablet-share --file /path/to/image.png      # share an existing PNG
tablet-share --window                       # Niri's window capture instead of a region
```

`--window` waits up to five minutes after you cancel, because Niri sends no
event for a cancelled capture.

### Retention

Age counts from when the server first received the image.

| Age | Folder | Shown on |
|-----|--------|----------|
| Under 7 days | `history/` | The gallery |
| 7 to 30 days | `archive/` | The archive page |
| 30 days or older | Deleted | Nowhere |

Cleanup runs on every upload and once a day. The daily run only happens while
you are logged in to the server unless lingering is on
(`sudo loginctl enable-linger $USER`); the installer tells you if it is off.
`latest.png` always points to the newest image.

```bash
ssh myserver '~/.local/bin/tablet-share-server maintain'     # clean up now
ssh myserver 'systemctl --user list-timers tablet-share-maintenance.timer'
```

## Development

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_selection test_render test_upscale
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s share -p 'test_*.py' -v
```

The share tests need only Python. [BACKLOG.md](BACKLOG.md) lists ideas I
haven't done yet.

## License

[MIT](LICENSE)
