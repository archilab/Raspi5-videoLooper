#!/usr/bin/env python3
"""
Finds and connects to Wi-Fi networks through NetworkManager's nmcli.

looper is allowed to do this by 50-looper-network-time.rules. Passwords go to nmcli on
its standard input, never on a command line, and are never logged. NetworkManager
stores them in a file only root can read.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

PROFILE_PREFIX = 'looper-'
CONNECT_WAIT = 30  # seconds nmcli waits for a connection


def _nmcli(*args, stdin=None, timeout=20):
    """Run nmcli, returning the finished process, or None if it couldn't be run"""
    try:
        return subprocess.run(['nmcli', *args], input=stdin, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        # Not the exception's text: it can include the standard input
        logger.error(f"nmcli {args[0]} could not run: {type(e).__name__}")
        return None


def _succeeded(result):
    return result is not None and result.returncode == 0


def _split_fields(line):
    """Split nmcli's terse output on ':', which it escapes inside values as '\\:'"""
    fields = ['']
    characters = iter(line)
    for character in characters:
        if character == '\\':
            fields[-1] += next(characters, '')
        elif character == ':':
            fields.append('')
        else:
            fields[-1] += character
    return fields


def _lines(result):
    return result.stdout.splitlines() if _succeeded(result) else []


def current_wifi():
    """The name of the connected Wi-Fi network, or None"""
    for line in _lines(_nmcli('-t', '-f', 'ACTIVE,SSID', 'device', 'wifi', 'list', '--rescan', 'no')):
        active, ssid = _split_fields(line)[:2]
        if active == 'yes':
            return ssid
    return None


def _active_wifi_profile():
    """The UUID of the active Wi-Fi profile, or None"""
    for line in _lines(_nmcli('-t', '-f', 'UUID,TYPE', 'connection', 'show', '--active')):
        uuid, kind = _split_fields(line)[:2]
        if kind == '802-11-wireless':
            return uuid
    return None


def scan():
    """Visible networks, strongest first, as dicts with 'ssid', 'signal' and 'security'"""
    best = {}
    result = _nmcli('-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', '--rescan', 'yes', timeout=30)
    for line in _lines(result):
        ssid, signal, security = _split_fields(line)[:3]
        if not ssid:  # A hidden network
            continue
        signal = int(signal) if signal.isdigit() else 0
        if ssid not in best or signal > best[ssid]['signal']:
            best[ssid] = {'ssid': ssid, 'signal': signal, 'security': security}
    return sorted(best.values(), key=lambda network: network['signal'], reverse=True)


def key_management(security):
    """
    The setting a network's security needs: None for an open network, or
    'unsupported' for types that need more than a password or are obsolete
    """
    if not security.strip():
        return None
    if '802.1X' in security or 'WEP' in security:
        return 'unsupported'
    if 'WPA1' in security or 'WPA2' in security:
        return 'wpa-psk'
    return 'sae'


def _profile_exists(name):
    return _succeeded(_nmcli('connection', 'show', name))


def _save_profile(name, ssid, password, key_mgmt, hidden):
    """Create a profile by typing into nmcli's editor, which keeps the password out of the process list"""
    # Not automatic until it has worked, so a wrong password can't keep retrying by itself.
    # With automatic on, the editor would also stop to ask for confirmation when saving.
    lines = ['set connection.autoconnect no', f'set 802-11-wireless.ssid {ssid}']
    if hidden:
        lines.append('set 802-11-wireless.hidden yes')
    if key_mgmt:
        lines.append(f'set 802-11-wireless-security.key-mgmt {key_mgmt}')
        lines.append(f'set 802-11-wireless-security.psk {password}')
    lines += ['save persistent', 'quit', '']
    return _succeeded(_nmcli('connection', 'edit', 'type', 'wifi', 'con-name', name, stdin='\n'.join(lines)))


def _ip_address(name):
    result = _nmcli('-g', 'IP4.ADDRESS', 'connection', 'show', name)
    return result.stdout.split('|')[0].split('/')[0].strip() if _succeeded(result) else ''


def connect(ssid, password=None, key_mgmt='wpa-psk', hidden=False):
    """
    Connect to a network and remember it. If that fails, the attempt is removed
    and the previous network is reconnected.
    Returns (success, message to show)
    """
    previous = _active_wifi_profile()
    name = f'{PROFILE_PREFIX}{ssid}'
    trial = f'{name}-new'
    if _profile_exists(trial):
        _nmcli('connection', 'delete', trial)

    if not _save_profile(trial, ssid, password, key_mgmt, hidden):
        return False, "Could not save the network's settings."

    if not _succeeded(_nmcli('--wait', str(CONNECT_WAIT), 'connection', 'up', trial, timeout=CONNECT_WAIT + 15)):
        _nmcli('connection', 'delete', trial)
        if previous and _succeeded(_nmcli('--wait', str(CONNECT_WAIT), 'connection', 'up', previous,
                                          timeout=CONNECT_WAIT + 15)):
            return False, f"Could not connect to {ssid}, so stayed on the previous network.\nCheck the password."
        return False, f"Could not connect to {ssid}.\nCheck the password."

    # Only now replace any earlier settings for this network
    if _profile_exists(name):
        _nmcli('connection', 'delete', name)
    _nmcli('connection', 'modify', trial, 'connection.id', name,
           'connection.autoconnect', 'yes', 'connection.autoconnect-priority', '10')
    address = _ip_address(name)
    return True, f"Connected to {ssid}." + (f"\nIP address: {address}" if address else "")
