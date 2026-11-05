"""Guards against shipping a broken set of files, like a module that's imported but missing"""

import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, make_tree

MODULES = sorted(p.name for p in ROOT.glob('*.py'))


class Packaging(unittest.TestCase):
    def test_every_local_import_exists(self):
        stdlib = set(sys.stdlib_module_names) | {'serial'}
        for module in MODULES:
            tree = ast.parse((ROOT / module).read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module]
                for name in names:
                    top = name.split('.')[0]
                    if top not in stdlib:
                        self.assertIn(f'{top}.py', MODULES, f'{module} imports {top}')

    def test_deploy_ships_every_module(self):
        files = re.search(r'FILES=\((.*?)\)', (ROOT / 'deploy.sh').read_text(), re.S).group(1).split()
        self.assertEqual(sorted(f for f in files if f.endswith('.py')), MODULES)

    def test_install_copies_every_module(self):
        copied = set()
        for line in (ROOT / 'install.sh').read_text().splitlines():
            if line.startswith('sudo cp -f'):
                copied.update(word for word in line.split() if word.endswith('.py'))
        self.assertEqual(sorted(copied), MODULES)

    def test_install_and_deploy_ship_the_rtc_rule(self):
        self.assertIn('99-looper-rtc.rules', (ROOT / 'install.sh').read_text())
        self.assertIn('99-looper-rtc.rules', (ROOT / 'deploy.sh').read_text())
        self.assertTrue((ROOT / '99-looper-rtc.rules').exists())


class CommandLine(unittest.TestCase):
    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)

    def test_help(self):
        self.assertEqual(self.run_cli('video_looper.py', '--help').returncode, 0)
        self.assertEqual(self.run_cli('time_sync.py', '--help').returncode, 0)

    def test_shows_the_active_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos = Path(tmp) / 'videos'
            always = '2000-01-01_to_2099-12-31_0000_to_2359'
            make_tree(videos, {always: {'a.mp4': ''}})
            result = self.run_cli('video_looper.py', '--test', '--videos-path', str(videos))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'Active folder: {always}', result.stdout)
        self.assertIn("['a.mp4']", result.stdout)

    def test_reports_no_active_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli('video_looper.py', '--test', '--videos-path', tmp)
        self.assertIn('No active folders found', result.stdout)

    def test_usb_preview_runs_without_changing_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            videos = Path(tmp) / 'videos'
            name = '2026-01-01_to_2026-01-02_0900_to_1800'
            make_tree(videos, {name: {'a.mp4': ''}})
            result = self.run_cli('video_looper.py', '--usb-sync-test', '--videos-path', str(videos))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((videos / name / 'a.mp4').exists())
