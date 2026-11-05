import logging
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

import network_setup

PASSWORD = 'correct horse'


class FakeNmcli:
    """Stands in for nmcli: profiles it knows about, and which activations fail"""

    def __init__(self, active=None, profiles=(), fail_up=(), fail_save=False):
        self.active = active
        self.profiles = set(profiles)
        self.fail_up = set(fail_up)
        self.fail_save = fail_save
        self.calls = []
        self.scan_output = ''
        self.stdin = []

    def __call__(self, cmd, input=None, **kwargs):
        args = cmd[1:]
        self.calls.append(args)
        if input is not None:
            self.stdin.append(input)
        return self.handle(args)

    @staticmethod
    def result(returncode=0, stdout=''):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr='')

    def handle(self, args):
        if args[:1] == ['--wait']:
            name = args[4]
            if name in self.fail_up:
                return self.result(4)
            self.active = name
            return self.result()
        if args[:4] == ['-t', '-f', 'UUID,TYPE', 'connection']:
            return self.result(stdout=f'{self.active}:802-11-wireless\nlo-id:loopback\n' if self.active else 'lo-id:loopback\n')
        if args[:3] == ['-t', '-f', 'SSID,SIGNAL,SECURITY']:
            return self.result(stdout=self.scan_output)
        if args[:2] == ['-g', 'IP4.ADDRESS']:
            return self.result(stdout='192.168.1.50/24 | fe80::1/64\n')
        if args[:2] == ['connection', 'show']:
            return self.result(0 if args[2] in self.profiles else 10)
        if args[:2] == ['connection', 'edit']:
            if self.fail_save:
                return self.result(1)
            self.profiles.add(args[5])
            return self.result()
        if args[:2] == ['connection', 'delete']:
            self.profiles.discard(args[2])
            return self.result()
        if args[:2] == ['connection', 'modify']:
            self.profiles.discard(args[2])
            self.profiles.add(args[4])
            return self.result()
        return self.result()


class NetworkTestCase(unittest.TestCase):
    def use(self, fake):
        patcher = mock.patch.object(network_setup.subprocess, 'run', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class Reading(NetworkTestCase):
    def test_splits_escaped_fields(self):
        self.assertEqual(network_setup._split_fields(r'yes:my\:net\\work'), ['yes', 'my:net\\work'])

    def test_current_wifi(self):
        fake = self.use(FakeNmcli())
        fake.handle = lambda args: fake.result(stdout='no:other\nyes:my\\:net\n')
        self.assertEqual(network_setup.current_wifi(), 'my:net')

    def test_not_connected(self):
        fake = self.use(FakeNmcli())
        fake.handle = lambda args: fake.result(stdout='no:other\n')
        self.assertIsNone(network_setup.current_wifi())

    def test_scan_drops_hidden_keeps_strongest_and_sorts(self):
        fake = self.use(FakeNmcli())
        fake.scan_output = ':90:WPA2\nweak:20:WPA2\nhome:40:WPA2\nhome:80:WPA2\nopen spot:70:\n'
        self.assertEqual(network_setup.scan(), [
            {'ssid': 'home', 'signal': 80, 'security': 'WPA2'},
            {'ssid': 'open spot', 'signal': 70, 'security': ''},
            {'ssid': 'weak', 'signal': 20, 'security': 'WPA2'},
        ])

    def test_nmcli_failing_or_missing_is_harmless(self):
        self.use(lambda *a, **k: FakeNmcli.result(8))
        self.assertEqual(network_setup.scan(), [])
        self.assertIsNone(network_setup.current_wifi())
        with mock.patch.object(network_setup.subprocess, 'run', side_effect=FileNotFoundError('nmcli')), \
                self.assertLogs('network_setup', logging.ERROR):
            self.assertEqual(network_setup.scan(), [])

    def test_key_management(self):
        for security, expected in (('', None), (' ', None), ('WPA2', 'wpa-psk'), ('WPA1 WPA2', 'wpa-psk'),
                                   ('WPA2 WPA3', 'wpa-psk'), ('WPA3', 'sae'), ('WEP', 'unsupported'),
                                   ('WPA2 802.1X', 'unsupported')):
            self.assertEqual(network_setup.key_management(security), expected, security)


class Connecting(NetworkTestCase):
    def test_success_is_saved_under_a_stable_name(self):
        fake = self.use(FakeNmcli(active='old-uuid'))
        ok, message = network_setup.connect('home', PASSWORD)
        self.assertTrue(ok)
        self.assertEqual(fake.profiles, {'looper-home'})
        self.assertIn('Connected to home', message)
        self.assertIn('192.168.1.50', message)

    def test_automatic_connection_is_only_switched_on_after_success(self):
        fake = self.use(FakeNmcli(active='old-uuid'))
        network_setup.connect('home', PASSWORD)
        self.assertIn('set connection.autoconnect no', fake.stdin[0])
        modify = [args for args in fake.calls if args[:2] == ['connection', 'modify']]
        self.assertEqual(modify, [['connection', 'modify', 'looper-home-new', 'connection.id', 'looper-home',
                                   'connection.autoconnect', 'yes', 'connection.autoconnect-priority', '10']])
        up = next(i for i, args in enumerate(fake.calls) if args[:1] == ['--wait'])
        self.assertLess(up, fake.calls.index(modify[0]))

    def test_failed_attempt_never_becomes_automatic(self):
        fake = self.use(FakeNmcli(active='old-uuid', fail_up=['looper-home-new']))
        network_setup.connect('home', PASSWORD)
        self.assertFalse(any(args[:2] == ['connection', 'modify'] for args in fake.calls))

    def test_password_is_never_on_a_command_line(self):
        fake = self.use(FakeNmcli())
        network_setup.connect('home', PASSWORD)
        self.assertFalse(any(PASSWORD in arg for args in fake.calls for arg in args))
        self.assertIn(f'set 802-11-wireless-security.psk {PASSWORD}', fake.stdin[0])

    def test_password_is_never_in_the_message_or_log(self):
        self.use(FakeNmcli(fail_up=['looper-home-new']))
        with self.assertNoLogs('network_setup', logging.INFO):
            ok, message = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertNotIn(PASSWORD, message)

    def test_a_timeout_does_not_log_the_password(self):
        def slow(cmd, input=None, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 20, output=input)
        self.use(slow)
        with self.assertLogs('network_setup', logging.ERROR) as logs:
            ok, _ = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertNotIn(PASSWORD, ''.join(logs.output))

    def test_editor_script_is_complete(self):
        fake = self.use(FakeNmcli())
        network_setup.connect('my net', PASSWORD)
        self.assertEqual(fake.stdin[0].splitlines(), [
            'set connection.autoconnect no',
            'set 802-11-wireless.ssid my net',
            'set 802-11-wireless-security.key-mgmt wpa-psk',
            f'set 802-11-wireless-security.psk {PASSWORD}',
            'save persistent',
            'quit',
        ])

    def test_open_network_has_no_security(self):
        fake = self.use(FakeNmcli())
        network_setup.connect('cafe', None, None)
        self.assertNotIn('security', fake.stdin[0])

    def test_hidden_network(self):
        fake = self.use(FakeNmcli())
        network_setup.connect('secret', PASSWORD, 'wpa-psk', hidden=True)
        self.assertIn('set 802-11-wireless.hidden yes', fake.stdin[0])

    def test_failure_removes_the_attempt_and_goes_back(self):
        fake = self.use(FakeNmcli(active='old-uuid', fail_up=['looper-home-new']))
        ok, message = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertEqual(fake.profiles, set())
        self.assertEqual(fake.active, 'old-uuid')
        self.assertIn('stayed on the previous network', message)

    def test_failure_with_no_previous_network(self):
        self.use(FakeNmcli(fail_up=['looper-home-new']))
        ok, message = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertNotIn('previous', message)

    def test_failure_going_back_is_reported(self):
        self.use(FakeNmcli(active='old-uuid', fail_up=['looper-home-new', 'old-uuid']))
        ok, message = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertNotIn('stayed on', message)

    def test_wrong_new_password_keeps_the_saved_settings(self):
        fake = self.use(FakeNmcli(active='looper-home', profiles=['looper-home'], fail_up=['looper-home-new']))
        ok, _ = network_setup.connect('home', 'wrong password')
        self.assertFalse(ok)
        self.assertEqual(fake.profiles, {'looper-home'})

    def test_right_new_password_replaces_the_saved_settings(self):
        fake = self.use(FakeNmcli(active='looper-home', profiles=['looper-home']))
        ok, _ = network_setup.connect('home', PASSWORD)
        self.assertTrue(ok)
        self.assertEqual(fake.profiles, {'looper-home'})
        self.assertIn(['connection', 'delete', 'looper-home'], fake.calls)

    def test_leftover_attempt_is_cleared_first(self):
        fake = self.use(FakeNmcli(profiles=['looper-home-new']))
        network_setup.connect('home', PASSWORD)
        self.assertEqual(fake.calls[1], ['connection', 'show', 'looper-home-new'])
        self.assertEqual(fake.calls[2], ['connection', 'delete', 'looper-home-new'])

    def test_save_failure_changes_nothing(self):
        fake = self.use(FakeNmcli(active='old-uuid', fail_save=True))
        ok, message = network_setup.connect('home', PASSWORD)
        self.assertFalse(ok)
        self.assertEqual(fake.active, 'old-uuid')
        self.assertFalse(any(args[:1] == ['--wait'] for args in fake.calls))
        self.assertIn('Could not save', message)
