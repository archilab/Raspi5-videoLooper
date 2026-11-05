"""Shared fakes, so the tests never touch the real clock, display, projector or VLC"""

from pathlib import Path
from types import SimpleNamespace

import hdmi_controller

ROOT = Path(__file__).resolve().parent.parent


def folder_name(month):
    """A valid schedule folder name, different for each month"""
    return f'2026-{month:02d}-01_to_2026-{month:02d}-02_0900_to_1800'


def make_tree(root, tree):
    """Create {folder: {file: content}} under root"""
    root.mkdir(parents=True, exist_ok=True)
    for folder, files in tree.items():
        (root / folder).mkdir()
        for name, content in files.items():
            (root / folder / name).write_text(content)


def read_tree(root):
    return {d.name: {f.name: f.read_text() for f in d.iterdir()} for d in root.iterdir()}


class FakeProcess:
    def __init__(self, stuck=False):
        self.alive = True
        self.stuck = stuck
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        if not self.stuck:
            self.alive = False

    def kill(self):
        self.alive = False
        self.killed = True

    def wait(self, timeout=None):
        import subprocess
        if self.alive and timeout is not None:
            raise subprocess.TimeoutExpired('vlc', timeout)
        return 0


class FakeCec:
    """Replaces subprocess.run and records the CEC commands sent"""

    def __init__(self):
        self.sent = []
        self.returncode = 0

    def __call__(self, cmd, input=None, **kwargs):
        if cmd[0] == '/x/cec-client':
            self.sent.append(input.strip())
            return SimpleNamespace(returncode=self.returncode, stdout='', stderr='')
        return SimpleNamespace(returncode=1, stdout='', stderr='')


def make_hdmi():
    hdmi = hdmi_controller.HDMIController()
    hdmi.cec_client_path = '/x/cec-client'
    return hdmi


class FakeProjector:
    def __init__(self):
        self.config = {}
        self.calls = []

    def load_config_from_file(self, path):
        self.config = {'enable_projector': 'disabled' not in open(path).read()}
        return True

    def get_default_config(self):
        return {'enable_projector': False}

    def connect(self):
        self.calls.append('connect')
        return True

    def start_projector(self):
        self.calls.append('start')
        return True

    def stop_projector(self):
        self.calls.append('stop')
        return True

    def disconnect(self):
        self.calls.append('disconnect')
