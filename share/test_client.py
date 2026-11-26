"""Check how the upload client reads its settings."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('tablet-share')
loader = importlib.machinery.SourceFileLoader('tablet_share', str(SCRIPT))
spec = importlib.util.spec_from_loader('tablet_share', loader)
client = importlib.util.module_from_spec(spec)
loader.exec_module(client)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Path(temp.name) / 'config'

    def test_config_file_with_comments_and_quotes(self):
        self.config.write_text('# my server\nTABLET_SHARE_HOST = box\nTABLET_SHARE_URL="https://box.lan/g/"\n')
        host, url, selector = client.load_settings(self.config, {})
        self.assertEqual((host, url), ('box', 'https://box.lan/g'))
        self.assertEqual(selector, str(client.DEFAULT_SELECTOR))
        self.assertTrue(client.DEFAULT_SELECTOR.name == 'shoot-select' and client.DEFAULT_SELECTOR.exists())

    def test_environment_overrides_file(self):
        self.config.write_text('TABLET_SHARE_HOST=box\nTABLET_SHARE_URL=http://box:8080\n')
        environ = {'TABLET_SHARE_HOST': 'other', 'TABLET_SHARE_SELECTOR': '/bin/true', 'HOME': '/x'}
        self.assertEqual(client.load_settings(self.config, environ), ('other', 'http://box:8080', '/bin/true'))

    def test_missing_settings_name_the_file(self):
        with self.assertRaisesRegex(RuntimeError, 'TABLET_SHARE_HOST and TABLET_SHARE_URL'):
            client.load_settings(self.config, {})
        self.config.write_text('nonsense\n')
        with self.assertRaisesRegex(RuntimeError, 'config:1'):
            client.load_settings(self.config, {})


if __name__ == '__main__':
    unittest.main()
