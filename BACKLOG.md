# Backlog

- **Startup time.** About 0.4 s passes between the shortcut and the frozen
  overlay: Python and GTK start first, then grim runs. Options: start grim
  before importing GTK (output names from `niri msg --json outputs`), keep a
  warm background process that only shows windows, or rewrite in a compiled
  language.
- Click a window to snap the selection to it.
- **PDF upscale speed.** Matching takes about one second per page, up to three
  pages per visible Okular window; most of it is FFTs, sliding-window sums, and
  resizing across about 50 zoom levels. Ideas: derive the zoom from the page
  edges visible on screen, remember each Okular window's zoom from the previous
  match, or check first the Okular window under the selection (Niri reports
  window positions) instead of the focused one.
- PDF upscale for other viewers: PDF.js in Zen (no D-Bus; would need the file
  from the browser), Papers/Evince (D-Bus exposes the document URI).
- PDF upscale for a selection spanning two pages in continuous mode.
- `tablet-share --retry` stops at the first failing receipt, so one screenshot
  that was deleted locally or rejected by the server blocks the rest of the
  queue. Tell connection failures from per-image ones, and set aside the latter.
