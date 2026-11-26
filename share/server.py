#!/usr/bin/env python3
"""Receive PNGs over SSH and maintain a static screenshot gallery.

The gallery is plain files: index.html, gallery.json, and the PNGs. Any static
web server can publish the folder; `serve` is a small one for setups without one.
"""
import argparse
import fcntl
import functools
import hashlib
import html
import http.server
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import time
import zlib

MAX_BYTES = 32 * 1024 * 1024
NAME = re.compile(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}-[a-f0-9]{8}\.png\Z')
DAY = 86400


def png_size(data):
    """Reject incomplete uploads before publishing a file."""
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Not a PNG')
    offset, size, saw_data = 8, None, False
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError('Truncated PNG')
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:end - 4]
        crc = struct.unpack('>I', data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError('PNG checksum mismatch')
        if size is None:
            if kind != b'IHDR' or length != 13:
                raise ValueError('Missing PNG header')
            size = struct.unpack('>II', payload[:8])
            if min(size) < 1 or max(size) > 32768 or size[0] * size[1] > 100_000_000:
                raise ValueError('PNG dimensions exceed limit')
        if kind == b'IDAT':
            saw_data = True
        if kind == b'IEND':
            if length or end != len(data) or not saw_data:
                raise ValueError('Invalid PNG end')
            return size
        offset = end
    raise ValueError('Incomplete PNG')


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def items(directory, prefix):
    result = []
    for path in directory.glob('*.png'):
        if path.is_symlink() or not path.is_file():
            continue
        # IHDR dimensions allow the browser to reserve space before lazy loading.
        with path.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or not header.startswith(b'\x89PNG\r\n\x1a\n'):
            continue
        width, height = struct.unpack('>II', header[16:24])
        result.append(dict(name=path.name, src=prefix + path.name,
                           width=width, height=height, timestamp=path.stat().st_mtime))
    return sorted(result, key=lambda item: (item['timestamp'], item['name']), reverse=True)


def figure(item, first=False):
    name, src = html.escape(item['name']), html.escape(item['src'], quote=True)
    loading = 'eager' if first else 'lazy'
    priority = ' fetchpriority="high"' if first else ''
    return (f'<figure data-name="{name}"><figcaption>{name}</figcaption>'
            f'<a href="{src}"><img src="{src}" alt="Screenshot {name}" '
            f'width="{item["width"]}" height="{item["height"]}" '
            f'loading="{loading}"{priority} decoding="async"></a></figure>')


POLL = '''<script>
let names = [...document.querySelectorAll('figure')].map(el => el.dataset.name).join('|');
async function refresh() {
  if (document.hidden) return;
  try {
    const response = await fetch('gallery.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const items = await response.json();
    const next = items.map(item => item.name).join('|');
    if (next !== names) {
      // Reuse existing nodes so polling doesn't reload images or interrupt dragging.
      const existing = new Map([...document.querySelectorAll('figure')].map(el => [el.dataset.name, el]));
      const nodes = items.map((item, i) => {
        if (existing.has(item.name)) return existing.get(item.name);
        const fig = document.createElement('figure'); fig.dataset.name = item.name;
        const caption = document.createElement('figcaption'); caption.textContent = item.name;
        const link = document.createElement('a'); link.href = item.src;
        const img = document.createElement('img');
        img.width = item.width; img.height = item.height;
        img.alt = 'Screenshot ' + item.name;
        img.loading = i === 0 ? 'eager' : 'lazy';
        if (i === 0) img.fetchPriority = 'high';
        img.decoding = 'async'; img.src = item.src;
        link.append(img); fig.append(caption, link); return fig;
      });
      document.querySelector('#gallery').replaceChildren(...nodes);
      document.querySelector('#empty').hidden = items.length !== 0;
      names = next;
    }
    document.querySelector('#status').textContent = '';
  } catch (err) {
    document.querySelector('#status').textContent = 'Could not refresh. Reconnecting…';
  }
}
setInterval(refresh, 5000);
document.addEventListener('visibilitychange', refresh);
</script>'''


def page(entries, archive=False):
    title = 'Drop archive' if archive else 'Drop'
    nav = '<a href="../">Recent screenshots</a>' if archive else '<a href="archive/">Archive</a>'
    note = 'Screenshots from days 7–30.' if archive else 'Last 7 days. Hold or drag an image to copy it.'
    pictures = '\n'.join(figure(item, i == 0) for i, item in enumerate(entries))
    empty = ' hidden' if entries else ''
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
html {{background: white; color: #111; color-scheme: light;}}
body {{font-family: sans-serif; max-width: 900px; margin: auto; padding: 1rem;}}
nav {{margin-bottom: 1rem;}} figure {{margin: 0 0 2rem;}}
figcaption {{font-weight: bold; margin: 1rem 0; overflow-wrap: anywhere;}}
img {{display: block; max-width: 100%; height: auto; border: 1px solid #ccc;}}
#status {{color: #666; font-size: .9rem;}}
</style></head><body><h1>{title}</h1><nav>{nav}</nav><p>{note}</p>
<p id="status" role="status"></p><p id="empty"{empty}>No screenshots here yet.</p>
<main id="gallery">{pictures}</main>{'' if archive else POLL}
</body></html>'''.encode()


def maintain(root, now=None):
    now = time.time() if now is None else now
    # Only managed image folders participate in retention, never other site files.
    for folder in ('history', 'archive'):
        for path in (root / folder).glob('*.png'):
            if path.is_symlink() or not path.is_file():
                continue
            age = now - path.stat().st_mtime
            if age >= 30 * DAY:
                path.unlink()
            elif age >= 7 * DAY and folder == 'history':
                destination = root / 'archive' / path.name
                if destination.exists():
                    raise ValueError(f'Archive collision: {path.name}')
                path.rename(destination)
    recent = items(root / 'history', 'history/')
    archive = items(root / 'archive', '')
    atomic_write(root / 'archive/index.html', page(archive, archive=True))
    atomic_write(root / 'index.html', page(recent))
    atomic_write(root / 'gallery.json', json.dumps(recent).encode())
    latest = root / 'latest.png'
    if recent or archive:
        target = recent[0]['src'] if recent else 'archive/' + archive[0]['name']
        temp = root / '.latest-next'
        temp.unlink(missing_ok=True)
        temp.symlink_to(target)
        os.replace(temp, latest)
    else:
        latest.unlink(missing_ok=True)
    return recent, archive


class GalleryHandler(http.server.SimpleHTTPRequestHandler):
    """Static files without directory listings; pages and JSON are revalidated on every load."""

    def list_directory(self, path):
        self.send_error(404)

    def end_headers(self):
        if not self.path.endswith('.png'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def make_server(root, bind, port):
    handler = functools.partial(GalleryHandler, directory=str(root))
    return http.server.ThreadingHTTPServer((bind, port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='gallery folder')
    sub = parser.add_subparsers(dest='command', required=True)
    upload = sub.add_parser('receive')
    upload.add_argument('name')
    upload.add_argument('sha256')
    sub.add_parser('maintain')
    web = sub.add_parser('serve', help='publish the gallery folder over HTTP')
    web.add_argument('--bind', default='127.0.0.1', help='address to listen on (default: 127.0.0.1)')
    web.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if args.command == 'serve':
        root = args.root.expanduser()
        root.mkdir(parents=True, exist_ok=True)
        with make_server(root, args.bind, args.port) as server:
            print(f'Serving {root} on http://{args.bind}:{args.port}/', flush=True)
            server.serve_forever()
        return
    data = None
    if args.command == 'receive':
        if not NAME.fullmatch(args.name) or not re.fullmatch('[a-f0-9]{64}', args.sha256):
            parser.error('Invalid image name or checksum')
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Screenshot exceeds 32 MiB')
        png_size(data)
        if hashlib.sha256(data).hexdigest() != args.sha256:
            raise ValueError('Upload checksum mismatch')
    root = args.root.expanduser()
    for directory in (root, root / 'history', root / 'archive'):
        directory.mkdir(parents=True, exist_ok=True)
    # The lock lives outside the web root.
    lock_path = root.parent / ('.' + root.name + '-maintenance.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if data is not None:
            destination = root / 'history' / args.name
            for candidate in (destination, root / 'archive' / args.name):
                if candidate.exists():
                    if hashlib.sha256(candidate.read_bytes()).hexdigest() != args.sha256:
                        raise ValueError('An image with this name already exists')
                    break
            else:
                atomic_write(destination, data)
            maintain(root)
            source = 'history/' if destination.exists() else 'archive/'
            print(json.dumps(dict(name=args.name, sha256=args.sha256, src=source + args.name)))
        else:
            recent, archive = maintain(root)
            print(f'Gallery: {len(recent)} recent, {len(archive)} archived')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(f'tablet-share-server: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
