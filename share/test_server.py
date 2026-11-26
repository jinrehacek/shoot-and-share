"""Exercise transfer failures, concurrent uploads, and retention using real files."""
import hashlib
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

SCRIPT = Path(__file__).with_name('server.py')
spec = importlib.util.spec_from_file_location('gallery_server', SCRIPT)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


PNG = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\xff')) + chunk(b'IEND', b'')
NAME = '2026-10-01_20-00-00-000001-1234abcd.png'


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'clipboard'

    def receive(self, data=PNG, name=NAME, digest=None):
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), 'receive', name,
                               digest or hashlib.sha256(data).hexdigest()], input=data, capture_output=True)

    def test_upload_is_atomic_and_idempotent(self):
        result = self.receive()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'history' / NAME).read_bytes(), PNG)
        stamp = (self.root / 'history' / NAME).stat().st_mtime_ns
        self.assertEqual(self.receive().returncode, 0)
        self.assertEqual((self.root / 'history' / NAME).stat().st_mtime_ns, stamp)
        self.assertEqual(json.loads(result.stdout)['src'], 'history/' + NAME)
        self.assertEqual((self.root / 'latest.png').read_bytes(), PNG)

    def test_incomplete_or_corrupt_upload_never_published(self):
        for data in (b'', PNG[:-4], PNG[:40] + b'broken', b'not a png'):
            result = self.receive(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / 'history' / NAME).exists())
        self.assertNotEqual(self.receive(digest='0' * 64).returncode, 0)
        self.assertNotEqual(self.receive(name='../escape.png').returncode, 0)

    def test_retention_boundaries_and_separate_lazy_archive(self):
        self.assertEqual(self.receive().returncode, 0)
        now = time.time()
        stamps = {'recent.png': now - 6 * server.DAY, 'archive.png': now - 7 * server.DAY,
                  'expire.png': now - 30 * server.DAY}
        for name, stamp in stamps.items():
            path = self.root / 'history' / name
            path.write_bytes(PNG)
            os.utime(path, (stamp, stamp))
        (self.root / 'keep.txt').write_text('unrelated')
        recent, archive = server.maintain(self.root, now)
        self.assertTrue((self.root / 'history/recent.png').exists())
        self.assertTrue((self.root / 'archive/archive.png').exists())
        self.assertFalse((self.root / 'history/expire.png').exists())
        self.assertTrue((self.root / 'keep.txt').exists())
        page = (self.root / 'index.html').read_text()
        self.assertNotIn('src="archive/', page)
        self.assertIn('loading="lazy"', page)
        self.assertIn('fetchpriority="high"', page)
        self.assertIn('archive.png', (self.root / 'archive/index.html').read_text())
        self.assertNotIn('<script>', (self.root / 'archive/index.html').read_text())
        # Archive keeps the original age and expires at 30 days, not 30 more days.
        server.maintain(self.root, now + 23 * server.DAY)
        self.assertFalse((self.root / 'archive/archive.png').exists())

    def test_simultaneous_uploads_do_not_lose_gallery_entries(self):
        processes = []
        for i in range(4):
            name = NAME.replace('000001', f'{i:06d}')
            proc = subprocess.Popen([sys.executable, str(SCRIPT), '--root', str(self.root), 'receive',
                                     name, hashlib.sha256(PNG).hexdigest()], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.stdin.write(PNG)
            proc.stdin.close()
            proc.stdin = None
            processes.append(proc)
        for proc in processes:
            _, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(len(json.loads((self.root / 'gallery.json').read_text())), 4)


    def test_root_is_required(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'maintain'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'--root', result.stderr)

    def test_serve_publishes_files_without_listings(self):
        self.assertEqual(self.receive().returncode, 0)
        httpd = server.make_server(self.root, '127.0.0.1', 0)
        self.addCleanup(httpd.server_close)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        base = f'http://127.0.0.1:{httpd.server_address[1]}/'
        with urllib.request.urlopen(base) as response:
            self.assertIn(NAME, response.read().decode())
            self.assertEqual(response.headers['Cache-Control'], 'no-cache')
        with urllib.request.urlopen(base + 'history/' + NAME) as response:
            self.assertEqual(response.read(), PNG)
            self.assertIsNone(response.headers['Cache-Control'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + 'history/')
        self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
