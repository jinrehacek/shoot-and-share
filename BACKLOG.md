# Backlog

- **Startup time.** About 0.4 s passes between the shortcut and the frozen
  overlay: Python and GTK start first, then grim runs. Options: start grim
  before importing GTK (output names from `niri msg --json outputs`), keep a
  warm background process that only shows windows, or rewrite in a compiled
  language.
- Start with the previous selection, like Niri's screenshot UI.
- Click a window to snap the selection to it.
- Use shoot-select for local-only screenshots (Print, Mod+Shift+S) too.
