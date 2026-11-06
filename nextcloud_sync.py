#!/usr/bin/env python3
"""
Keeps the local video folders matching a folder on a Nextcloud server, over WebDAV.

It connects with either a public share link or an account with an app password. Like USB
sync, the source is the source of truth, but this runs during playback, over a network
that can fail. So nothing is deleted unless everything else worked, downloads resume, and
a file or new folder only appears once it's complete. Passwords and share links aren't logged.
"""

import fcntl
import json
import logging
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ElementTree
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests

import scheduler
from constants import (
    NEXTCLOUD_CONFIG_FILE, NEXTCLOUD_DEFAULT_INTERVAL, NEXTCLOUD_FIRST_CHECK_DELAY, NEXTCLOUD_FREE_SPACE_MARGIN,
    NEXTCLOUD_LOCK_FILE, NEXTCLOUD_STATUS_FILE, NEXTCLOUD_TRIGGER_FILE, NEXTCLOUD_USB_FILE,
    PROJECTOR_CONFIG_FILES, VIDEO_EXTENSIONS, DEFAULT_VIDEOS_PATH
)
from sync_plan import make_plan

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = (15, 60)  # seconds to connect, and between bytes
DOWNLOAD_CHUNK = 1024 * 1024  # bytes
PROPFIND_BODY = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
                 '<d:getcontentlength/><d:getlastmodified/><d:getetag/></d:prop></d:propfind>')
SHARE_LINK = re.compile(r'^(https?://[^?#]*?)(?:/index\.php)?/s/([^/?#]+)/?(?:[?#].*)?$')


class NextcloudError(Exception):
    """A problem to show to the person, whose message never contains a secret"""


# ------------------------------------------------------------------- Settings

def _check_url(url, label):
    parsed = urlparse(url)
    local = parsed.hostname in ('localhost', '127.0.0.1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise ValueError(f"{label} must start with https://")
    if not parsed.hostname:
        raise ValueError(f"{label} has no server name")


def make_config(fields):
    """Build settings from share_url, or from server, username and password. Raises ValueError."""
    interval = str(fields.get('interval') or NEXTCLOUD_DEFAULT_INTERVAL)
    if not interval.isdigit() or not 1 <= int(interval) <= 1440:
        raise ValueError("interval must be 1 to 1440 minutes")
    config = {'interval': int(interval), 'enabled': bool(fields.get('enabled', True)),
              'password': fields.get('password') or ''}

    share_url = (fields.get('share_url') or '').strip()
    server = (fields.get('server') or '').strip().rstrip('/')
    if bool(share_url) == bool(server):
        raise ValueError("set either share_url, or server with username and password")

    if share_url:
        _check_url(share_url, "The share link")
        if not SHARE_LINK.match(share_url):
            raise ValueError("The share link should look like https://cloud.example.com/s/abc123")
        config.update(mode='share', share_url=share_url)
    else:
        _check_url(server, "The server")
        username = (fields.get('username') or '').strip()
        if not username or not config['password']:
            raise ValueError("An account needs a username and an app password")
        config.update(mode='account', server=server, username=username,
                      folder=(fields.get('folder') or '').strip().strip('/'))
    return config


def parse_config_text(text):
    """Read the key=value lines of a nextcloud.txt file. Raises ValueError."""
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key = key.strip().lower()
        if not separator or key not in ('share_url', 'server', 'username', 'password', 'folder',
                                        'interval', 'enabled'):
            raise ValueError(f"unknown line starting with '{key[:20]}'")
        fields[key] = value.strip()
    if 'enabled' in fields:
        fields['enabled'] = fields['enabled'].lower() not in ('false', 'no', '0', 'off')
    return make_config(fields)


def load_config():
    """The saved settings, or None if there aren't any usable ones"""
    try:
        with open(NEXTCLOUD_CONFIG_FILE) as f:
            return make_config(json.load(f))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning(f"Ignoring the Nextcloud settings: {type(e).__name__}")
        return None


def save_config(config):
    """Save settings in a file only looper can read"""
    temp_path = f"{NEXTCLOUD_CONFIG_FILE}.tmp"
    descriptor = os.open(temp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as f:
        json.dump(config, f)
    os.replace(temp_path, NEXTCLOUD_CONFIG_FILE)


def is_enabled():
    config = load_config()
    return bool(config and config['enabled'])


def import_from_usb(usb_mounts):
    """
    Save the settings from a nextcloud.txt on a USB drive, if they're new.
    Turning Nextcloud off in the menu stays off, unless the file itself changes.
    Returns a message to show, or None if there was nothing to do.
    """
    for mount in usb_mounts:
        path = Path(mount) / NEXTCLOUD_USB_FILE
        try:
            text = path.read_text()
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            return f"Could not read {NEXTCLOUD_USB_FILE} on the USB drive: {type(e).__name__}"
        try:
            config = parse_config_text(text)
        except ValueError as e:
            return f"Problem in {NEXTCLOUD_USB_FILE} on the USB drive:\n{e}"

        current = load_config()
        without_enabled = lambda settings: {k: v for k, v in settings.items() if k != 'enabled'}
        if current and without_enabled(current) == without_enabled(config):
            return None
        save_config(config)
        return (f"Nextcloud settings imported from the USB drive.\nNextcloud sync is "
                f"{'on, so USB video sync is off' if config['enabled'] else 'off'}.\n"
                f"Remove {NEXTCLOUD_USB_FILE} from the drive, since it contains the password.")
    return None


# ------------------------------------------------------------------- Status

def write_status(ok, message):
    status = {'time': datetime.now().strftime('%Y-%m-%d %H:%M'), 'ok': ok, 'message': message}
    try:
        with open(f"{NEXTCLOUD_STATUS_FILE}.tmp", 'w') as f:
            json.dump(status, f)
        os.replace(f"{NEXTCLOUD_STATUS_FILE}.tmp", NEXTCLOUD_STATUS_FILE)
    except OSError as e:
        logger.warning(f"Could not save the Nextcloud status: {e}")


def read_status():
    try:
        with open(NEXTCLOUD_STATUS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def status_line():
    """A short summary for the menu"""
    config = load_config()
    if not config:
        return "not set up"
    if not config['enabled']:
        return "off"
    status = read_status()
    if not status:
        return "on, not checked yet"
    return f"on, {'OK' if status['ok'] else 'PROBLEM'} at {status['time'][-5:]}"


def request_sync():
    """Ask the background service to check now"""
    try:
        Path(NEXTCLOUD_TRIGGER_FILE).touch()
    except OSError as e:
        logger.warning(f"Could not request a sync: {e}")


# ------------------------------------------------------------------- Server

def _endpoints(config):
    """The WebDAV addresses to try, as (base URL, login)"""
    password = config['password']
    if config['mode'] == 'share':
        prefix, token = SHARE_LINK.match(config['share_url']).groups()
        return [(f"{prefix}/public.php/dav/files/{token}/", ('anonymous', password) if password else None),
                (f"{prefix}/public.php/webdav/", (token, password))]
    path = ''.join(f"{quote(part, safe='')}/" for part in config['folder'].split('/') if part)
    return [(f"{config['server']}/remote.php/dav/files/{quote(config['username'], safe='')}/{path}",
             (config['username'], password))]


def _safe_name(name):
    """Refuse names that could write outside the folder they belong in"""
    return bool(name) and name not in ('.', '..') and not name.startswith('.') and not set(name) & set('/\\\0')


def _wanted_file(name):
    return _safe_name(name) and (Path(name).suffix.lower() in VIDEO_EXTENSIONS or name in PROJECTOR_CONFIG_FILES)


class Client:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.base = None

    def _request(self, method, url, **options):
        try:
            return self.session.request(method, url, timeout=REQUEST_TIMEOUT, **options)
        except requests.RequestException as e:
            # Not the exception's text, which includes the share link
            raise NextcloudError(f"Could not reach the server ({type(e).__name__})")

    def _propfind(self, url):
        return self._request('PROPFIND', url, data=PROPFIND_BODY,
                             headers={'Depth': '1', 'Content-Type': 'application/xml'})

    def connect(self):
        """Find the WebDAV address that works"""
        refused = False
        last_status = None
        for base, login in _endpoints(self.config):
            self.session.auth = login
            status = self._propfind(base).status_code
            if status == 207:
                self.base = base
                return
            refused = refused or status in (401, 403)
            last_status = status
        if refused:
            raise NextcloudError("The server refused the login or share link.\nCheck the settings and password.")
        raise NextcloudError(f"The server doesn't offer that folder (answered {last_status}).")

    def _url(self, *names):
        return self.base + '/'.join(quote(name, safe='') for name in names)

    def _list(self, *names):
        response = self._propfind(self._url(*names))
        if response.status_code != 207:
            raise NextcloudError(f"The server couldn't list a folder (answered {response.status_code}).")
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError:
            raise NextcloudError("The server sent a folder listing that can't be read.")

        entries = []
        for item in root.findall('{DAV:}response'):
            href = item.findtext('{DAV:}href') or ''
            prop = item.find('{DAV:}propstat/{DAV:}prop')
            if prop is None:
                continue
            modified = prop.findtext('{DAV:}getlastmodified')
            try:
                mtime = int(parsedate_to_datetime(modified).timestamp()) if modified else 0
                size = int(prop.findtext('{DAV:}getcontentlength') or 0)
            except (TypeError, ValueError):
                raise NextcloudError("The server sent a folder listing that can't be read.")
            entries.append({
                'name': unquote(href.rstrip('/').rsplit('/', 1)[-1]),
                'is_dir': prop.find('{DAV:}resourcetype/{DAV:}collection') is not None,
                'size': size, 'mtime': mtime, 'etag': (prop.findtext('{DAV:}getetag') or '').strip(),
            })
        return entries

    def list_folders(self):
        """Valid schedule folders with at least one video, as {folder: {file name: details}}"""
        if not self.base:
            self.connect()
        folders = {}
        for entry in self._list():
            if not entry['is_dir'] or not _safe_name(entry['name']) or not scheduler.parse_folder_name(entry['name']):
                continue
            files = {item['name']: item for item in self._list(entry['name'])
                     if not item['is_dir'] and _wanted_file(item['name'])}
            if any(Path(name).suffix.lower() in VIDEO_EXTENSIONS for name in files):
                folders[entry['name']] = files
        return folders

    def download(self, folder, entry, directory):
        """Download a file to a hidden name, resuming if possible, and return that path"""
        name = entry['name']
        part = directory / f".{name}.part"
        etag_file = directory / f".{name}.part.etag"
        offset = 0
        if entry['etag'] and part.exists() and etag_file.exists() and etag_file.read_text() == entry['etag']:
            offset = part.stat().st_size
        if offset > entry['size']:
            offset = 0

        if offset < entry['size'] or entry['size'] == 0:
            headers = {'Range': f'bytes={offset}-', 'If-Range': entry['etag']} if offset else {}
            etag_file.write_text(entry['etag'])
            try:
                with self._request('GET', self._url(folder, name), headers=headers, stream=True) as response:
                    if response.status_code not in (200, 206):
                        raise NextcloudError(f"The server couldn't send {name} (answered {response.status_code}).")
                    with open(part, 'ab' if response.status_code == 206 else 'wb') as f:
                        for chunk in response.iter_content(DOWNLOAD_CHUNK):
                            f.write(chunk)
                        f.flush()
                        os.fsync(f.fileno())
            except requests.RequestException as e:
                raise NextcloudError(f"The download of {name} was interrupted ({type(e).__name__}).")

        if part.stat().st_size != entry['size']:
            raise NextcloudError(f"The download of {name} was incomplete.")
        os.utime(part, (entry['mtime'], entry['mtime']))
        return part


# ------------------------------------------------------------------- Sync

def _video_names(files):
    return {name.lower() for name in files if Path(name).suffix.lower() in VIDEO_EXTENSIONS}


def _local_folders(local_path):
    if not local_path.exists():
        return {}
    return {path.name: {video.name.lower() for video in videos}
            for path, videos in scheduler.get_all_valid_folders(local_path)}


def _needs_download(directory, entry):
    try:
        stat = (directory / entry['name']).stat()
    except OSError:
        return True
    return stat.st_size != entry['size'] or int(stat.st_mtime) != entry['mtime']


def _finish_downloads(client, folder, files, directory):
    """Download every changed file, then put them all in place together. Returns how many."""
    changed = [entry for entry in files.values() if _needs_download(directory, entry)]
    parts = [(client.download(folder, entry, directory), directory / entry['name']) for entry in changed]
    for part, destination in parts:
        os.replace(part, destination)
        (part.parent / f"{part.name}.etag").unlink(missing_ok=True)
    return len(changed)


def _remove_old_files(files, directory):
    """Remove videos and projector settings no longer on the server, and abandoned downloads"""
    for path in directory.iterdir():
        unwanted = (path.is_file() and not path.name.startswith('.') and path.name not in files
                    and (path.suffix.lower() in VIDEO_EXTENSIONS or path.name in PROJECTOR_CONFIG_FILES))
        abandoned = path.name.startswith('.') and path.name.endswith(('.part', '.part.etag')) \
            and path.name.split('.part')[0][1:] not in files
        if unwanted or abandoned:
            path.unlink()


def preview(config, local_path):
    """What a sync would do, without changing anything. Raises NextcloudError."""
    remote = Client(config).list_folders()
    plan = make_plan({name: _video_names(files) for name, files in remote.items()}, _local_folders(local_path))
    return remote, plan


def sync(client, local_path):
    """Make the local folders match the server. Returns (success, message). Raises NextcloudError."""
    remote = client.list_folders()
    if not remote:
        return True, "No valid folders on Nextcloud, so nothing changed."

    local_path.mkdir(parents=True, exist_ok=True)
    plan = make_plan({name: _video_names(files) for name, files in remote.items()}, _local_folders(local_path))

    # Enough room for everything before starting, since nothing old is removed until the end
    existing = {new: old for old, new in plan['rename']}
    needed = sum(entry['size'] for name, files in remote.items() for entry in files.values()
                 if _needs_download(local_path / existing.get(name, name), entry))
    free = shutil.disk_usage(local_path).free
    if needed + NEXTCLOUD_FREE_SPACE_MARGIN > free:
        raise NextcloudError(f"Not enough disk space: {needed // 2**20} MB to download, {free // 2**20} MB free.")

    errors = []
    renamed = downloaded = removed = 0
    for old_name, new_name in plan['rename']:
        try:
            (local_path / old_name).rename(local_path / new_name)
            renamed += 1
        except OSError as e:
            errors.append(f"Could not rename a folder: {e}")

    for name in plan['update'] + [new_name for _, new_name in plan['rename']]:
        directory = local_path / name
        try:
            directory.mkdir(exist_ok=True)
            downloaded += _finish_downloads(client, name, remote[name], directory)
            _remove_old_files(remote[name], directory)
        except (NextcloudError, OSError) as e:
            errors.append(str(e))

    for name in plan['copy']:
        # Hidden until complete, so a partly downloaded folder can never play
        incoming = local_path / f".incoming-{name}"
        try:
            incoming.mkdir(exist_ok=True)
            downloaded += _finish_downloads(client, name, remote[name], incoming)
            incoming.rename(local_path / name)
        except (NextcloudError, OSError) as e:
            errors.append(str(e))

    if errors:
        if plan['delete']:
            logger.warning(f"Keeping old folders because of errors: {plan['delete']}")
        return False, f"{errors[0]}\nOld folders were kept, and this retries at the next check."

    for name in plan['delete']:
        shutil.rmtree(local_path / name)
        removed += 1
    wanted_incoming = {f".incoming-{name}" for name in plan['copy']}
    for path in local_path.glob('.incoming-*'):
        if path.name not in wanted_incoming:
            shutil.rmtree(path)

    if not (downloaded or renamed or removed):
        return True, f"Up to date with {len(remote)} folder(s)."
    return True, f"Downloaded {downloaded} file(s), renamed {renamed} and removed {removed} folder(s)."


def run_sync(config, local_path):
    """Run one sync, unless another is running, and record the result. Returns (success, message)."""
    lock = open(NEXTCLOUD_LOCK_FILE, 'a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False, "Another sync is already running."
        try:
            ok, message = sync(Client(config), Path(local_path))
        except NextcloudError as e:
            ok, message = False, str(e)
        except OSError as e:
            ok, message = False, f"Problem with the local files: {e}"
        write_status(ok, message)
        if ok:
            print(f"Nextcloud: {message}", flush=True)
        else:
            logger.error(f"Nextcloud sync: {message}")
        return ok, message
    finally:
        lock.close()


# ------------------------------------------------------------------- Background service

class Schedule:
    """Decides when the next check is due"""

    def __init__(self, now):
        self.next_check = now + NEXTCLOUD_FIRST_CHECK_DELAY

    def due(self, now, trigger_requested):
        return trigger_requested or now >= self.next_check

    def checked(self, now, interval_minutes):
        self.next_check = now + interval_minutes * 60


def run_service(local_path):
    """Check regularly, reading the settings each time so the menu's changes apply straight away"""
    schedule = Schedule(time.monotonic())
    while True:
        config = load_config()
        trigger = Path(NEXTCLOUD_TRIGGER_FILE)
        requested = trigger.exists()
        if config and config['enabled']:
            if schedule.due(time.monotonic(), requested):
                trigger.unlink(missing_ok=True)
                run_sync(config, local_path)
                schedule.checked(time.monotonic(), config['interval'])
        elif requested:
            trigger.unlink(missing_ok=True)
        time.sleep(5)


def describe_plan(plan):
    lines = [f"  - Rename folder: {old} -> {new}" for old, new in plan['rename']]
    lines += [f"  - Download folder: {name}" for name in plan['copy']]
    lines += [f"  - Update folder: {name}" for name in plan['update']]
    lines += [f"  - Delete folder: {name}" for name in plan['delete']]
    return lines


def command_line(action, videos_path=None):
    """The --nextcloud options of video_looper.py. Returns the exit code."""
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler(sys.stderr)])
    local_path = Path(videos_path or DEFAULT_VIDEOS_PATH)

    if action == 'service':
        run_service(local_path)
        return 0

    config = load_config()
    if action == 'status':
        print(f"Nextcloud: {status_line()}")
        status = read_status()
        if status:
            print(f"Last check at {status['time']}: {status['message']}")
        if config:
            print(f"Connected with: {'share link' if config['mode'] == 'share' else 'account'}")
            print(f"Checks every {config['interval']} minute(s)")
        return 0

    if not config:
        print("✗ Nextcloud isn't set up. Use the boot menu, or nextcloud.txt on a USB drive.")
        return 1

    if action == 'test':
        try:
            remote, plan = preview(config, local_path)
        except NextcloudError as e:
            print(f"✗ {e}")
            return 1
        print(f"✓ Connected, and found {len(remote)} valid folder(s).")
        if remote:
            print("If synced now, would:")
            print('\n'.join(describe_plan(plan)))
        else:
            print("With no valid folders, a sync changes nothing.")
        return 0

    ok, message = run_sync(config, local_path)
    print(f"{'✓' if ok else '✗'} {message}")
    return 0 if ok else 1
