"""Runs against a real HTTP server speaking WebDAV, on this machine, with a temporary local folder"""

import base64
import json
import os
import stat
import tempfile
import threading
import unittest
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

import nextcloud_sync
from nextcloud_sync import NextcloudError, make_config, parse_config_text
from tests.helpers import folder_name

FA, FB, FC, FD = (folder_name(month) for month in range(1, 5))
MTIME = 1_700_000_000


class FakeNextcloud:
    """The files on the server, and the faults it should show"""

    def __init__(self):
        self.tree = {}
        self.mtimes = {}
        self.base = '/remote.php/dav/files/player/Videos/'
        self.login = 'player:apppass'
        self.requests = []
        self.fail_listing = None
        self.fail_download = {}
        self.cut_download = {}
        self.ignore_range = False

    def add(self, folder, name, content, mtime=MTIME):
        self.tree.setdefault(folder, {})[name] = content.encode() if isinstance(content, str) else content
        self.mtimes[(folder, name)] = mtime


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def cloud(self):
        return self.server.cloud

    def _authorised(self):
        if self.cloud.login is None:
            return True
        return self.headers.get('Authorization') == 'Basic ' + base64.b64encode(self.cloud.login.encode()).decode()

    def _parts(self):
        path = unquote(self.path)
        if not path.startswith(self.cloud.base):
            return None
        return [part for part in path[len(self.cloud.base):].split('/') if part]

    def _respond(self, status, body=b'', headers=()):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _entry(self, href, is_dir, size=0, mtime=MTIME, etag=''):
        kind = '<d:collection/>' if is_dir else ''
        details = '' if is_dir else f'<d:getcontentlength>{size}</d:getcontentlength><d:getetag>"{escape(etag)}"</d:getetag>'
        return (f'<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>'
                f'<d:resourcetype>{kind}</d:resourcetype><d:getlastmodified>{formatdate(mtime, usegmt=True)}</d:getlastmodified>'
                f'{details}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')

    def do_PROPFIND(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.cloud.requests.append(('PROPFIND', self.path))
        if not self._authorised():
            return self._respond(401)
        parts = self._parts()
        if parts is None:
            return self._respond(404)
        if self.cloud.fail_listing and parts == self.cloud.fail_listing:
            return self._respond(500)
        entries = [self._entry(self.path, True)]
        if not parts:
            entries += [self._entry(f'{self.cloud.base}{quote(name)}/', True) for name in self.cloud.tree]
            entries += self.server.extra_root
        elif parts[0] in self.cloud.tree:
            for name, content in self.cloud.tree[parts[0]].items():
                entries.append(self._entry(f'{self.cloud.base}{quote(parts[0])}/{quote(name)}', False, len(content),
                                           self.cloud.mtimes[(parts[0], name)], f'{parts[0]}/{name}/{hash(content)}'))
            entries += self.server.extra_folder
        else:
            return self._respond(404)
        body = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">' + ''.join(entries) + '</d:multistatus>').encode()
        self._respond(207, body, [('Content-Type', 'application/xml')])

    def do_GET(self):
        self.cloud.requests.append(('GET', self.path, self.headers.get('Range')))
        if not self._authorised():
            return self._respond(401)
        folder, name = self._parts()
        if (folder, name) in self.cloud.fail_download:
            return self._respond(self.cloud.fail_download[(folder, name)])
        content = self.cloud.tree[folder][name]
        byte_range = self.headers.get('Range')
        if byte_range and not self.cloud.ignore_range:
            start = int(byte_range.split('=')[1].rstrip('-'))
            status, body = 206, content[start:]
        else:
            status, body = 200, content
        cut = self.cloud.cut_download.pop((folder, name), None)
        if cut is not None:
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body[:cut])
            self.wfile.flush()
            self.close_connection = True
            return
        self._respond(status, body)


class NextcloudTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.local = self.tmp / 'videos'
        self.local.mkdir()
        self.cloud = FakeNextcloud()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.cloud = self.cloud
        self.server.extra_root = []
        self.server.extra_folder = []
        thread = threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.address = f'http://127.0.0.1:{self.server.server_address[1]}'
        for name, value in (('NEXTCLOUD_CONFIG_FILE', self.tmp / 'nextcloud.conf'),
                            ('NEXTCLOUD_STATUS_FILE', self.tmp / 'status'),
                            ('NEXTCLOUD_TRIGGER_FILE', self.tmp / 'trigger'),
                            ('NEXTCLOUD_LOCK_FILE', self.tmp / 'lock'),
                            ('NEXTCLOUD_FREE_SPACE_MARGIN', 0)):
            patcher = mock.patch.object(nextcloud_sync, name, str(value) if isinstance(value, Path) else value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def config(self, **fields):
        return make_config({'server': self.address, 'username': 'player', 'password': 'apppass',
                            'folder': 'Videos', **fields})

    def client(self):
        return nextcloud_sync.Client(self.config())

    def sync(self):
        return nextcloud_sync.sync(self.client(), self.local)

    def add_local(self, folder, name, content, mtime=MTIME):
        directory = self.local / folder
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text(content)
        os.utime(path, (mtime, mtime))
        return path

    def local_tree(self):
        return {d.name: {f.name: f.read_text() for f in d.iterdir()} for d in self.local.iterdir()}


class Settings(unittest.TestCase):
    def test_share_link_forms(self):
        for link in ('https://cloud.test/s/abc', 'https://cloud.test/s/abc/', 'https://cloud.test/index.php/s/abc',
                     'https://cloud.test/nextcloud/s/abc', 'https://cloud.test/s/abc?dir=/'):
            self.assertEqual(make_config({'share_url': link})['mode'], 'share', link)

    def test_rejected_settings(self):
        for fields in ({}, {'share_url': 'https://a.test/s/x', 'server': 'https://a.test'},
                       {'share_url': 'http://cloud.test/s/abc'}, {'share_url': 'https://cloud.test/files'},
                       {'server': 'http://cloud.test', 'username': 'u', 'password': 'p'},
                       {'server': 'https://cloud.test', 'password': 'p'}, {'server': 'https://cloud.test', 'username': 'u'},
                       {'share_url': 'https://a.test/s/x', 'interval': '0'},
                       {'share_url': 'https://a.test/s/x', 'interval': 'often'}):
            with self.assertRaises(ValueError, msg=fields):
                make_config(fields)

    def test_error_messages_never_contain_the_password(self):
        with self.assertRaises(ValueError) as caught:
            make_config({'server': 'http://cloud.test', 'username': 'u', 'password': 'topsecret'})
        self.assertNotIn('topsecret', str(caught.exception))

    def test_defaults(self):
        config = make_config({'share_url': 'https://a.test/s/x'})
        self.assertEqual((config['interval'], config['enabled'], config['password']), (15, True, ''))

    def test_text_file(self):
        config = parse_config_text('# comment\n\nserver = https://cloud.test/\nusername=player\n'
                                   'password=a=b c\nfolder=/Videos/Looper/\ninterval=5\nenabled=false\n')
        self.assertEqual((config['server'], config['password'], config['folder'], config['interval'], config['enabled']),
                         ('https://cloud.test', 'a=b c', 'Videos/Looper', 5, False))

    def test_text_file_rejects_unknown_lines_without_showing_them(self):
        with self.assertRaises(ValueError) as caught:
            parse_config_text('share_url=https://a.test/s/x\nmy secret password line\n')
        self.assertIn('unknown line', str(caught.exception))

    def test_endpoints(self):
        share = nextcloud_sync._endpoints(make_config({'share_url': 'https://a.test/nc/index.php/s/abc', 'password': 'p'}))
        self.assertEqual(share, [('https://a.test/nc/public.php/dav/files/abc/', ('anonymous', 'p')),
                                 ('https://a.test/nc/public.php/webdav/', ('abc', 'p'))])
        open_share = nextcloud_sync._endpoints(make_config({'share_url': 'https://a.test/s/abc'}))
        self.assertIsNone(open_share[0][1])
        account = nextcloud_sync._endpoints(make_config({'server': 'https://a.test', 'username': 'a b', 'password': 'p',
                                                         'folder': 'My Videos/Looper'}))
        self.assertEqual(account[0][0], 'https://a.test/remote.php/dav/files/a%20b/My%20Videos/Looper/')


class SavedSettings(NextcloudTestCase):
    def test_saved_file_is_private(self):
        nextcloud_sync.save_config(self.config())
        mode = stat.S_IMODE(os.stat(nextcloud_sync.NEXTCLOUD_CONFIG_FILE).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(nextcloud_sync.load_config()['username'], 'player')

    def test_missing_or_damaged_settings_count_as_off(self):
        self.assertFalse(nextcloud_sync.is_enabled())
        Path(nextcloud_sync.NEXTCLOUD_CONFIG_FILE).write_text('not json')
        with self.assertLogs('nextcloud_sync', 'WARNING'):
            self.assertFalse(nextcloud_sync.is_enabled())

    def test_status_lines(self):
        self.assertEqual(nextcloud_sync.status_line(), 'not set up')
        nextcloud_sync.save_config(self.config(enabled=False))
        self.assertEqual(nextcloud_sync.status_line(), 'off')
        nextcloud_sync.save_config(self.config())
        self.assertEqual(nextcloud_sync.status_line(), 'on, not checked yet')
        nextcloud_sync.write_status(True, 'fine')
        self.assertRegex(nextcloud_sync.status_line(), r'^on, OK at \d\d:\d\d$')
        nextcloud_sync.write_status(False, 'bad')
        self.assertRegex(nextcloud_sync.status_line(), r'^on, PROBLEM at ')

    def usb(self, text):
        drive = self.tmp / 'usb'
        drive.mkdir(exist_ok=True)
        (drive / 'nextcloud.txt').write_text(text)
        return [drive]

    def test_import(self):
        message = nextcloud_sync.import_from_usb(self.usb('share_url=https://a.test/s/x\npassword=topsecret\n'))
        self.assertIn('imported', message)
        self.assertIn('Remove nextcloud.txt', message)
        self.assertNotIn('topsecret', message)
        self.assertTrue(nextcloud_sync.is_enabled())

    def test_import_without_a_file_or_with_the_same_settings(self):
        self.assertIsNone(nextcloud_sync.import_from_usb([self.tmp]))
        drive = self.usb('share_url=https://a.test/s/x\n')
        nextcloud_sync.import_from_usb(drive)
        self.assertIsNone(nextcloud_sync.import_from_usb(drive))

    def test_turned_off_in_the_menu_stays_off_until_the_file_changes(self):
        drive = self.usb('share_url=https://a.test/s/x\n')
        nextcloud_sync.import_from_usb(drive)
        config = nextcloud_sync.load_config()
        config['enabled'] = False
        nextcloud_sync.save_config(config)
        self.assertIsNone(nextcloud_sync.import_from_usb(drive))
        self.assertFalse(nextcloud_sync.is_enabled())
        self.assertIn('imported', nextcloud_sync.import_from_usb(self.usb('share_url=https://a.test/s/y\n')))
        self.assertTrue(nextcloud_sync.is_enabled())

    def test_import_with_enabled_false(self):
        nextcloud_sync.import_from_usb(self.usb('share_url=https://a.test/s/x\nenabled=false\n'))
        self.assertFalse(nextcloud_sync.is_enabled())

    def test_bad_file_changes_nothing(self):
        message = nextcloud_sync.import_from_usb(self.usb('server=http://cloud.test\n'))
        self.assertIn('Problem in nextcloud.txt', message)
        self.assertIsNone(nextcloud_sync.load_config())


class Connecting(NextcloudTestCase):
    def share_config(self, password=''):
        return make_config({'share_url': f'{self.address}/s/abc', 'password': password})

    def test_new_share_address_is_tried_first(self):
        self.cloud.base = '/public.php/dav/files/abc/'
        self.cloud.login = None
        self.cloud.add(FA, 'a.mp4', 'video')
        self.assertEqual(list(nextcloud_sync.Client(self.share_config()).list_folders()), [FA])

    def test_falls_back_to_the_older_share_address(self):
        self.cloud.base = '/public.php/webdav/'
        self.cloud.login = 'abc:'
        self.cloud.add(FA, 'a.mp4', 'video')
        self.assertEqual(list(nextcloud_sync.Client(self.share_config()).list_folders()), [FA])

    def test_share_password(self):
        self.cloud.base = '/public.php/dav/files/abc/'
        self.cloud.login = 'anonymous:sharepass'
        self.cloud.add(FA, 'a.mp4', 'video')
        self.assertEqual(list(nextcloud_sync.Client(self.share_config('sharepass')).list_folders()), [FA])

    def test_wrong_login_is_explained(self):
        self.cloud.login = 'player:other'
        with self.assertRaisesRegex(NextcloudError, 'refused the login'):
            self.client().list_folders()

    def test_wrong_folder_is_explained(self):
        client = nextcloud_sync.Client(self.config(folder='Elsewhere'))
        with self.assertRaisesRegex(NextcloudError, 'answered 404'):
            client.list_folders()

    def test_unreachable_server_never_shows_the_link(self):
        self.server.shutdown()
        self.server.server_close()
        client = nextcloud_sync.Client(make_config({'share_url': f'{self.address}/s/secrettoken'}))
        with self.assertRaises(NextcloudError) as caught:
            client.list_folders()
        self.assertNotIn('secrettoken', str(caught.exception))
        self.assertIn('Could not reach', str(caught.exception))


class Listing(NextcloudTestCase):
    def test_keeps_only_valid_folders_with_videos_and_wanted_files(self):
        self.cloud.add(FA, 'a.mp4', 'video')
        self.cloud.add(FA, 'projector.txt', 'x')
        self.cloud.add(FA, 'notes.docx', 'x')
        self.cloud.add(FB, 'notes.txt', 'no video here')
        self.cloud.add('holiday pictures', 'a.mp4', 'video')
        self.cloud.add('2026-01-01_to_2026-01-02_0900_to_1800_backup', 'a.mp4', 'video')
        folders = self.client().list_folders()
        self.assertEqual(list(folders), [FA])
        self.assertEqual(sorted(folders[FA]), ['a.mp4', 'projector.txt'])

    def test_names_with_spaces_and_umlauts(self):
        self.cloud.add(FA, 'Größe 1 & 2.mp4', 'video')
        self.assertEqual(self.sync()[0], True)
        self.assertEqual(self.local_tree()[FA], {'Größe 1 & 2.mp4': 'video'})

    def test_dangerous_names_are_ignored(self):
        self.cloud.add(FA, 'a.mp4', 'video')
        base = self.cloud.base
        handler = Handler._entry
        make = lambda href, size=5: handler(None, href, False, size, MTIME, 'x')
        self.server.extra_folder = [make(f'{base}{FA}/..%2F..%2Fevil.mp4'), make(f'{base}{FA}/.hidden.mp4'),
                                    make(f'{base}{FA}/a%5Cb.mp4')]
        self.server.extra_root = [handler(None, f'{base}..%2F2026-05-01_to_2026-05-02_0900_to_1800/', True)]
        folders = self.client().list_folders()
        self.assertEqual(list(folders), [FA])
        self.assertEqual(list(folders[FA]), ['a.mp4'])


class Syncing(NextcloudTestCase):
    def test_new_folder(self):
        self.cloud.add(FA, 'a.mp4', 'video', mtime=MTIME)
        self.cloud.add(FA, 'projector.txt', 'x')
        ok, message = self.sync()
        self.assertTrue(ok)
        self.assertIn('Downloaded 2', message)
        self.assertEqual(self.local_tree(), {FA: {'a.mp4': 'video', 'projector.txt': 'x'}})
        self.assertEqual(int((self.local / FA / 'a.mp4').stat().st_mtime), MTIME)

    def test_second_sync_downloads_nothing(self):
        self.cloud.add(FA, 'a.mp4', 'video')
        self.sync()
        self.cloud.requests.clear()
        ok, message = self.sync()
        self.assertIn('Up to date with 1', message)
        self.assertFalse([r for r in self.cloud.requests if r[0] == 'GET'])

    def test_changed_file_is_replaced(self):
        self.add_local(FA, 'a.mp4', 'old')
        self.cloud.add(FA, 'a.mp4', 'new content')
        self.sync()
        self.assertEqual(self.local_tree()[FA]['a.mp4'], 'new content')

    def test_same_size_with_another_date_is_replaced(self):
        self.add_local(FA, 'a.mp4', 'aaaaa', mtime=MTIME - 100)
        self.cloud.add(FA, 'a.mp4', 'bbbbb')
        self.sync()
        self.assertEqual(self.local_tree()[FA]['a.mp4'], 'bbbbb')

    def test_removed_files_and_other_files(self):
        self.add_local(FA, 'gone.mp4', 'x')
        self.add_local(FA, 'projector.conf', 'x')
        self.add_local(FA, 'notes.txt', 'keep me')
        self.cloud.add(FA, 'a.mp4', 'video')
        self.sync()
        self.assertEqual(self.local_tree()[FA], {'a.mp4': 'video', 'notes.txt': 'keep me'})

    def test_folder_missing_from_the_server_is_removed(self):
        self.add_local(FB, 'b.mp4', 'x')
        self.cloud.add(FA, 'a.mp4', 'video')
        self.sync()
        self.assertEqual(sorted(self.local_tree()), [FA])

    def test_redated_folder_is_renamed_not_downloaded(self):
        self.add_local(FA, 'a.mp4', 'video')
        self.cloud.add(FB, 'a.mp4', 'video')
        ok, message = self.sync()
        self.assertIn('renamed 1', message)
        self.assertEqual(sorted(self.local_tree()), [FB])
        self.assertFalse([r for r in self.cloud.requests if r[0] == 'GET'])

    def test_no_valid_folders_changes_nothing(self):
        self.add_local(FA, 'a.mp4', 'x')
        self.cloud.add('not a schedule', 'a.mp4', 'video')
        ok, message = self.sync()
        self.assertTrue(ok)
        self.assertIn('nothing changed', message)
        self.assertEqual(sorted(self.local_tree()), [FA])

    def test_preview_changes_nothing(self):
        self.add_local(FB, 'b.mp4', 'x')
        self.cloud.add(FA, 'a.mp4', 'video')
        before = self.local_tree()
        remote, plan = nextcloud_sync.preview(self.config(), self.local)
        self.assertEqual(list(remote), [FA])
        self.assertEqual(plan, {'update': [], 'copy': [FA], 'rename': [], 'delete': [FB]})
        self.assertEqual(self.local_tree(), before)


class Failures(NextcloudTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(nextcloud_sync, 'DOWNLOAD_CHUNK', 100)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_listing_failure_changes_nothing(self):
        self.add_local(FB, 'b.mp4', 'keep')
        self.cloud.add(FA, 'a.mp4', 'video')
        self.cloud.fail_listing = [FA]
        with self.assertRaisesRegex(NextcloudError, 'answered 500'):
            self.sync()
        self.assertEqual(self.local_tree(), {FB: {'b.mp4': 'keep'}})

    def test_damaged_listing_changes_nothing(self):
        self.add_local(FB, 'b.mp4', 'keep')
        self.server.extra_root = ['<not closed']
        with self.assertRaisesRegex(NextcloudError, "can't be read"):
            self.sync()
        self.assertEqual(sorted(self.local_tree()), [FB])

    def test_failed_download_keeps_old_folders_and_old_video(self):
        self.add_local(FA, 'a.mp4', 'old video')
        self.add_local(FC, 'c.mp4', 'keep me')
        self.cloud.add(FA, 'a.mp4', 'new video!')
        self.cloud.add(FB, 'b.mp4', 'video')
        self.cloud.fail_download[(FA, 'a.mp4')] = 503
        ok, message = self.sync()
        self.assertFalse(ok)
        self.assertIn('Old folders were kept', message)
        tree = self.local_tree()
        self.assertEqual(tree[FA]['a.mp4'], 'old video')
        self.assertEqual(tree[FC], {'c.mp4': 'keep me'})

    def test_new_folder_stays_hidden_until_complete(self):
        self.cloud.add(FA, 'a.mp4', 'video one')
        self.cloud.add(FA, 'b.mp4', 'video two')
        self.cloud.fail_download[(FA, 'b.mp4')] = 503
        ok, _ = self.sync()
        self.assertFalse(ok)
        self.assertFalse((self.local / FA).exists())
        self.assertEqual([p.name for p in self.local.iterdir()], [f'.incoming-{FA}'])
        del self.cloud.fail_download[(FA, 'b.mp4')]
        self.assertTrue(self.sync()[0])
        self.assertEqual(sorted(p.name for p in self.local.iterdir()), [FA])
        self.assertEqual(sorted(self.local_tree()[FA]), ['a.mp4', 'b.mp4'])

    def test_files_in_a_folder_are_replaced_together(self):
        self.add_local(FA, 'a.mp4', 'old a')
        self.add_local(FA, 'b.mp4', 'old b')
        self.cloud.add(FA, 'a.mp4', 'new a!')
        self.cloud.add(FA, 'b.mp4', 'new b!')
        self.cloud.fail_download[(FA, 'b.mp4')] = 503
        self.sync()
        self.assertEqual({k: v for k, v in self.local_tree()[FA].items() if not k.startswith('.')},
                         {'a.mp4': 'old a', 'b.mp4': 'old b'})

    def test_interrupted_download_resumes(self):
        content = 'x' * 500 + 'y' * 500
        self.cloud.add(FA, 'a.mp4', content)
        self.cloud.cut_download[(FA, 'a.mp4')] = 500
        ok, message = self.sync()
        self.assertFalse(ok)
        self.assertIn('a.mp4', message)
        self.cloud.requests.clear()
        self.assertTrue(self.sync()[0])
        self.assertEqual(self.local_tree()[FA]['a.mp4'], content)
        ranges = [r[2] for r in self.cloud.requests if r[0] == 'GET']
        self.assertEqual(ranges, ['bytes=500-'])

    def test_server_that_ignores_resuming_still_ends_up_right(self):
        content = 'x' * 500 + 'y' * 500
        self.cloud.add(FA, 'a.mp4', content)
        self.cloud.cut_download[(FA, 'a.mp4')] = 500
        self.sync()
        self.cloud.ignore_range = True
        self.assertTrue(self.sync()[0])
        self.assertEqual(self.local_tree()[FA]['a.mp4'], content)

    def test_changed_file_does_not_resume_the_old_download(self):
        self.cloud.add(FA, 'a.mp4', 'x' * 1000)
        self.cloud.cut_download[(FA, 'a.mp4')] = 500
        self.sync()
        self.cloud.add(FA, 'a.mp4', 'z' * 1000)
        self.cloud.requests.clear()
        self.assertTrue(self.sync()[0])
        self.assertEqual(self.local_tree()[FA]['a.mp4'], 'z' * 1000)
        self.assertEqual([r[2] for r in self.cloud.requests if r[0] == 'GET'], [None])

    def test_no_temporary_files_left_after_success(self):
        self.cloud.add(FA, 'a.mp4', 'x' * 1000)
        self.cloud.cut_download[(FA, 'a.mp4')] = 500
        self.sync()
        self.sync()
        self.assertEqual(os.listdir(self.local / FA), ['a.mp4'])

    def test_not_enough_disk_space_changes_nothing(self):
        self.add_local(FB, 'b.mp4', 'keep')
        self.cloud.add(FA, 'a.mp4', 'video')
        usage = mock.Mock(free=1)
        with mock.patch.object(nextcloud_sync.shutil, 'disk_usage', return_value=usage), \
                self.assertRaisesRegex(NextcloudError, 'Not enough disk space'):
            self.sync()
        self.assertEqual(self.local_tree(), {FB: {'b.mp4': 'keep'}})

    def test_space_margin_is_counted(self):
        self.cloud.add(FA, 'a.mp4', 'video')
        with mock.patch.object(nextcloud_sync, 'NEXTCLOUD_FREE_SPACE_MARGIN', 10 ** 15), \
                self.assertRaisesRegex(NextcloudError, 'Not enough disk space'):
            self.sync()

    def test_abandoned_incoming_folder_is_cleared(self):
        (self.local / f'.incoming-{FD}').mkdir()
        self.cloud.add(FA, 'a.mp4', 'video')
        self.assertTrue(self.sync()[0])
        self.assertEqual(sorted(p.name for p in self.local.iterdir()), [FA])


class RunningAndStatus(NextcloudTestCase):
    def test_result_is_recorded(self):
        self.cloud.add(FA, 'a.mp4', 'video')
        with mock.patch('builtins.print'):
            self.assertTrue(nextcloud_sync.run_sync(self.config(), self.local)[0])
        self.assertTrue(nextcloud_sync.read_status()['ok'])

    def test_failure_is_recorded_and_logged_without_secrets(self):
        with self.assertLogs('nextcloud_sync', 'ERROR') as logs:
            ok, _ = nextcloud_sync.run_sync(self.config(password='wrongpassword'), self.local)
        self.assertFalse(ok)
        self.assertFalse(nextcloud_sync.read_status()['ok'])
        self.assertNotIn('wrongpassword', ''.join(logs.output))
        self.assertNotIn('wrongpassword', json.dumps(nextcloud_sync.read_status()))

    def test_only_one_sync_at_a_time(self):
        import fcntl
        with open(nextcloud_sync.NEXTCLOUD_LOCK_FILE, 'a') as other:
            fcntl.flock(other, fcntl.LOCK_EX)
            ok, message = nextcloud_sync.run_sync(self.config(), self.local)
        self.assertFalse(ok)
        self.assertIn('already running', message)

    def test_schedule(self):
        schedule = nextcloud_sync.Schedule(1000)
        self.assertFalse(schedule.due(1000, False))
        self.assertTrue(schedule.due(1000, True))
        self.assertTrue(schedule.due(1000 + nextcloud_sync.NEXTCLOUD_FIRST_CHECK_DELAY, False))
        schedule.checked(2000, 15)
        self.assertFalse(schedule.due(2899, False))
        self.assertTrue(schedule.due(2900, False))

    def test_trigger_file(self):
        nextcloud_sync.request_sync()
        self.assertTrue(Path(nextcloud_sync.NEXTCLOUD_TRIGGER_FILE).exists())

    def command(self, action):
        with mock.patch('builtins.print') as printed:
            code = nextcloud_sync.command_line(action, str(self.local))
        return code, '\n'.join(' '.join(str(a) for a in call.args) for call in printed.call_args_list)

    def test_command_line_without_settings(self):
        self.assertIn('not set up', self.command('status')[1])
        self.assertEqual(self.command('test')[0], 1)
        self.assertEqual(self.command('sync')[0], 1)

    def test_command_line_test_and_sync(self):
        nextcloud_sync.save_config(self.config())
        self.cloud.add(FA, 'a.mp4', 'video')
        self.add_local(FB, 'b.mp4', 'x')
        code, output = self.command('test')
        self.assertEqual(code, 0)
        self.assertIn(f'Download folder: {FA}', output)
        self.assertIn(f'Delete folder: {FB}', output)
        self.assertEqual(sorted(self.local_tree()), [FB])
        self.assertEqual(self.command('sync')[0], 0)
        self.assertEqual(sorted(self.local_tree()), [FA])

    def test_status_never_shows_the_password_or_link(self):
        nextcloud_sync.save_config(make_config({'share_url': 'https://a.test/s/secrettoken', 'password': 'topsecret'}))
        output = self.command('status')[1]
        self.assertIn('share link', output)
        self.assertNotIn('secrettoken', output)
        self.assertNotIn('topsecret', output)
