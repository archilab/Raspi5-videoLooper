import os
import pty
import select
import sys
import tempfile
import termios
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import boot_menu
import console
from tests.helpers import folder_name, make_tree

HEADER = 'Set RTC Time\n' + '=' * 60 + '\n\n'


class MenuTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tty = self.tmp / 'tty'
        patcher = mock.patch.object(console, 'CONSOLE_PATH', str(self.tty))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.player = mock.Mock(current_process=None)
        self.time_sync = mock.Mock()
        self.time_sync.ntp_enabled.return_value = False
        self.menu = boot_menu.BootMenu(self.tmp / 'videos', self.player, self.time_sync)

    def screen(self):
        return self.tty.read_text().replace(console.CLEAR_SCREEN, '<clear>')


class TimeEntry(MenuTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch('time.sleep'),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def enter(self, answers):
        """Run the prompts with these answers; a missing answer times out. Returns the prompts."""
        answers = iter(answers)
        prompts = []

        def fake_input(prompt, low, high, timeout=60):
            prompts.append((prompt, low, high))
            return next(answers, None)

        with mock.patch.object(self.menu, '_get_numeric_input', fake_input):
            self.menu._enter_and_set_time()
        return prompts

    def test_refused_while_ntp_is_on(self):
        self.time_sync.ntp_enabled.return_value = True
        with mock.patch('time_entry.request_time_set') as request:
            prompts = self.enter([2026, 1, 1, 0, 0])
        self.assertEqual(prompts, [])
        request.assert_not_called()
        self.assertIn('NTP is on', self.screen())

    def test_prompts_and_result(self):
        with mock.patch('time_entry.request_time_set', return_value=True) as request:
            prompts = self.enter([2026, 2, 28, 7, 5])
        request.assert_called_once_with('2026-02-28 07:05:00')
        self.assertEqual(prompts[0], (HEADER + 'Enter Year (e.g., 2026):\n', 2000, 2099))
        self.assertEqual(prompts[2], (HEADER + 'Year: 2026\nMonth: 2\n\nEnter Day (1-28):\n', 1, 28))
        self.assertEqual(prompts[4], (HEADER + 'Year: 2026\nMonth: 2\nDay: 28\nHour: 7\n\nEnter Minute (0-59):\n', 0, 59))
        self.assertIn('Time set successfully!\n2026-02-28 07:05:00', self.screen())

    def test_days_per_month(self):
        for year, month, days in ((2026, 2, 28), (2028, 2, 29), (2000, 2, 29), (2026, 4, 30), (2026, 11, 30), (2026, 12, 31)):
            prompts = self.enter([year, month])
            self.assertEqual(prompts[2][2], days, (year, month))

    def test_cancelled_entry_sends_nothing(self):
        with mock.patch('time_entry.request_time_set') as request:
            self.enter([2026])
        request.assert_not_called()
        self.assertIn('Cancelled', self.screen())

    def test_failure_is_shown(self):
        with mock.patch('time_entry.request_time_set', return_value=False), self.assertLogs('boot_menu', 'ERROR'):
            self.enter([2026, 1, 1, 0, 0])
        self.assertIn('Failed to set time', self.screen())

    def test_hold_lasts_until_the_result_is_shown(self):
        hold = mock.Mock()
        order = []
        hold.close.side_effect = lambda: order.append('released')
        with mock.patch('time_entry.acquire_hold', return_value=hold), \
                mock.patch.object(self.menu, '_enter_and_set_time', lambda: order.append('entry')):
            self.menu.handle_manual_time_setting()
        self.assertEqual(order, ['entry', 'released'])

    def test_hold_released_if_entry_crashes(self):
        hold = mock.Mock()
        with mock.patch('time_entry.acquire_hold', return_value=hold), \
                mock.patch.object(self.menu, '_enter_and_set_time', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.menu.handle_manual_time_setting()
        hold.close.assert_called_once()


class Screens(MenuTestCase):
    def test_menu(self):
        self.menu._show_menu_screen(5)
        self.assertEqual(self.screen(), '<clear>\n' + '=' * 60 + '\nVideo Looper - Boot Menu\n' + '=' * 60 +
                         '\n\nSelect an option:\n\n  1. Start Demo Mode\n  2. Set RTC Time\n  3. Set Wi-Fi\n  4. Time source\n  5. Nextcloud\n\n'
                         '  Press 1 to 5, or Enter to continue...\n\n  Auto-continuing in 5 second(s)...\n\n')

    def test_countdown_end_and_no_countdown(self):
        self.menu._show_menu_screen(0)
        self.assertIn('Auto-continuing...\n', self.screen())
        self.menu._show_menu_screen()
        self.assertNotIn('Auto-continuing', self.screen())

    def test_prompt_and_messages(self):
        self.menu._show_numeric_prompt('P', '12', 'ok')
        self.assertEqual(self.screen(), '<clear>P\n\nInput: 12\nok')
        self.menu._show_feedback('hi')
        self.assertTrue(self.screen().endswith('\n\nhi\n'))
        with mock.patch('time.sleep'):
            self.menu.show_message('msg', 0)
        self.assertEqual(self.screen(), '<clear>\n' + '=' * 60 + '\nmsg\n' + '=' * 60 + '\n')

    def test_missing_console_is_harmless(self):
        with mock.patch.object(console, 'CONSOLE_PATH', str(self.tmp / 'missing' / 'tty')):
            self.assertFalse(console.show_on_console('x'))
            self.menu._show_menu_screen(1)

    def test_folder_list(self):
        make_tree(self.tmp / 'videos', {folder_name(2): {'clip.mp4': 'x' * 1024}})
        with mock.patch('time.sleep'), mock.patch('builtins.print'), \
                mock.patch.object(self.menu, 'display_boot_menu', return_value='demo') as boot:
            self.assertEqual(self.menu.display_folder_info_on_screen(), 'demo')
        boot.assert_called_once()
        self.assertIn('Found 1 valid loop folder(s)', self.screen())
        self.assertIn('Schedule: 2026-02-01 to 2026-02-02, 09:00 to 18:00', self.screen())
        self.assertIn('clip.mp4 (0.0 MB)', self.screen())


    def test_folder_list_shows_every_window(self):
        make_tree(self.tmp / 'videos', {'2026-02-01_to_2026-02-02_0500_to_0900_and_1600_to_2300': {'clip.mp4': ''}})
        with mock.patch('time.sleep'), mock.patch('builtins.print'), \
                mock.patch.object(self.menu, 'display_boot_menu'):
            self.menu.display_folder_info_on_screen()
        self.assertIn('Schedule: 2026-02-01 to 2026-02-02, 05:00 to 09:00 and 16:00 to 23:00', self.screen())


class MenuKeys(MenuTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('network_setup.current_wifi', return_value='homenet')
        patcher.start()
        self.addCleanup(patcher.stop)

    def press(self, *keys):
        with mock.patch('time.sleep'), mock.patch.object(self.menu, '_setup_terminal_input'), \
                mock.patch.object(self.menu, '_restore_terminal_input'), \
                mock.patch.object(self.menu, 'get_char_blocking', side_effect=list(keys)), \
                mock.patch.object(self.menu, 'handle_manual_time_setting') as set_time:
            return self.menu.display_boot_menu(), set_time

    def test_three_and_four_use_the_hold(self):
        for key, method in (('3', '_set_wifi'), ('4', '_set_time_source'), ('5', '_set_nextcloud')):
            hold = mock.Mock()
            seen = []
            with mock.patch('time_entry.acquire_hold', return_value=hold), \
                    mock.patch.object(self.menu, method, lambda: seen.append(hold.close.called)):
                self.assertIsNone(self.press(key)[0])
            self.assertEqual(seen, [False])
            hold.close.assert_called_once()

    def test_menu_shows_current_wifi_and_time_source(self):
        self.press('\r')
        self.assertIn('3. Set Wi-Fi (now: homenet)', self.screen())
        self.assertIn('4. Time source (now: RTC only)', self.screen())
        self.time_sync.ntp_enabled.return_value = True
        self.press('\r')
        self.assertIn('4. Time source (now: NTP)', self.screen())

    def test_menu_without_wifi(self):
        with mock.patch('network_setup.current_wifi', return_value=None):
            self.press('\r')
        self.assertIn('3. Set Wi-Fi (now: not connected)', self.screen())

    def test_one_starts_demo(self):
        self.assertEqual(self.press('1')[0], 'demo')

    def test_two_sets_time(self):
        result, set_time = self.press('2')
        self.assertIsNone(result)
        set_time.assert_called_once()

    def test_enter_continues(self):
        self.assertIsNone(self.press('\r')[0])

    def test_invalid_key_shows_the_menu_again(self):
        self.assertEqual(self.press('x', None, '1')[0], 'demo')

    def test_countdown_runs_out(self):
        moments = iter([0, 0, 25, 25, 25, 25])
        with mock.patch('time.time', lambda: next(moments)), mock.patch.object(self.menu, 'get_char_blocking', return_value=None):
            self.assertIsNone(self.menu.display_boot_menu())


class RealTerminal(MenuTestCase):
    """Runs against a real pseudo-terminal, like the console"""

    def setUp(self):
        super().setUp()
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        stdin = os.fdopen(self.slave, 'r')
        self.addCleanup(stdin.close)
        patcher = mock.patch.object(sys, 'stdin', stdin)
        patcher.start()
        self.addCleanup(patcher.stop)

    def drain(self):
        output = b''
        while select.select([self.master], [], [], 0.1)[0]:
            output += os.read(self.master, 4096)
        return output

    def test_newlines_return_to_the_left_edge(self):
        self.assertTrue(self.menu._setup_terminal_input())
        os.write(self.slave, b'a\nb\n')
        self.assertEqual(self.drain(), b'a\r\nb\r\n')

    def test_raw_input_with_no_echo(self):
        self.menu._setup_terminal_input()
        os.write(self.master, b'1')
        self.assertEqual(self.menu.get_char_blocking(timeout=1.0), '1')
        self.assertEqual(self.drain(), b'')
        lflag = termios.tcgetattr(self.slave)[3]
        self.assertFalse(lflag & termios.ICANON)
        self.assertFalse(lflag & termios.ISIG, 'Ctrl+C must be a plain key, not a signal')

    def test_settings_are_restored(self):
        def settings():
            attrs = termios.tcgetattr(self.slave)
            attrs[3] &= ~getattr(termios, 'PENDIN', 0)  # macOS sets this one by itself
            return attrs[:4]

        before = settings()
        self.menu._setup_terminal_input()
        self.menu._restore_terminal_input()
        self.assertEqual(settings(), before)

    def type_keys(self, keys):
        def typing():
            for key in keys:
                time.sleep(0.05)
                os.write(self.master, key.encode())

        thread = threading.Thread(target=typing)
        thread.start()
        self.addCleanup(thread.join)

    def numeric(self, keys, low, high, timeout=3):
        self.type_keys(keys)
        return self.menu._get_numeric_input('P', low, high, timeout=timeout)

    def test_full_value_is_accepted_without_enter(self):
        self.assertEqual(self.numeric('2026', 2000, 2099), 2026)

    def test_short_value_needs_enter(self):
        self.assertEqual(self.numeric('5\r', 1, 12), 5)

    def test_enter_is_seen_immediately(self):
        """Enter must not wait for another key, which is what text-mode stdin does"""
        self.menu._setup_terminal_input()
        self.type_keys('\r')
        self.assertEqual(self.menu.get_char_blocking(timeout=2), '\r')

    def test_backspace(self):
        self.assertEqual(self.numeric('2\x7f7\r', 1, 12), 7)

    def test_out_of_range_then_retry(self):
        self.assertEqual(self.numeric('99\r\r07', 1, 12), 7)

    def test_enter_alone_and_ctrl_c_cancel(self):
        self.assertIsNone(self.numeric('\r', 1, 12))
        self.assertIsNone(self.numeric('\x03', 1, 12))

    def text(self, keys, **options):
        """Type into the text entry, returning its result"""
        self.type_keys(keys)
        return self.menu._get_text_input('P', timeout=3, **options)

    def test_text_entry(self):
        self.assertEqual(self.text('my net 5\r'), 'my net 5')

    def test_text_entry_keeps_umlauts_and_symbols(self):
        self.assertEqual(self.text('pä$s"wö#rd\r'), 'pä$s"wö#rd')

    def test_text_entry_backspace(self):
        self.assertEqual(self.text('abd\x7fc\r'), 'abc')

    def test_text_entry_empty(self):
        self.assertEqual(self.text('\r'), '')

    def test_text_entry_cancels(self):
        self.assertIsNone(self.text('abc\x03'))
        self.assertIsNone(self.menu._get_text_input('P', timeout=0.2))

    def test_esc_cancels_but_arrow_keys_do_not(self):
        self.type_keys('a')
        def escape_later():
            time.sleep(0.2)
            os.write(self.master, b'\x1b')
        thread = threading.Thread(target=escape_later)
        thread.start()
        self.addCleanup(thread.join)
        self.assertIsNone(self.menu._get_text_input('P', timeout=3))

    def test_arrow_key_is_ignored(self):
        self.addCleanup(lambda: None)
        def typing():
            time.sleep(0.05)
            os.write(self.master, b'a')
            time.sleep(0.05)
            os.write(self.master, b'\x1b[A')
            time.sleep(0.15)
            os.write(self.master, b'b\r')
        thread = threading.Thread(target=typing)
        thread.start()
        self.addCleanup(thread.join)
        self.assertEqual(self.menu._get_text_input('P', timeout=3), 'ab')

    def test_secret_is_hidden_until_tab(self):
        screens = []
        real = boot_menu.show_on_console
        with mock.patch.object(boot_menu, 'show_on_console', side_effect=lambda t: (screens.append(t), real(t))[1]):
            self.assertEqual(self.text('topsecret\t\r', secret=True), 'topsecret')
        self.assertFalse(any('topsecret' in s for s in screens[:-1]))
        self.assertIn('*********', screens[-2])
        self.assertIn('topsecret', screens[-1])

    def test_get_key(self):
        self.type_keys('x2')
        self.assertEqual(self.menu._get_key('12', timeout=3), '2')
        self.type_keys('\r')
        self.assertIsNone(self.menu._get_key('12', timeout=3))
        self.assertIsNone(self.menu._get_key('12', timeout=0.2))

    def test_timeout_cancels(self):
        self.assertIsNone(self.menu._get_numeric_input('P', 1, 12, timeout=0.2))


class WifiSetup(MenuTestCase):
    NETWORKS = [{'ssid': 'home', 'signal': 90, 'security': 'WPA2'},
                {'ssid': 'cafe', 'signal': 70, 'security': ''},
                {'ssid': 'office', 'signal': 50, 'security': 'WPA2 802.1X'}]

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch('time.sleep'),
                        mock.patch('network_setup.scan', return_value=self.NETWORKS),
                        mock.patch('network_setup.connect', return_value=(True, 'Connected to home.'))):
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
        import network_setup
        self.connect = network_setup.connect

    def run_wifi(self, key, *texts):
        with mock.patch.object(self.menu, '_get_key', return_value=key), \
                mock.patch.object(self.menu, '_get_text_input', side_effect=list(texts)) as text:
            self.menu._set_wifi()
        return text

    def test_secured_network(self):
        self.run_wifi('1', 'goodpassword')
        self.connect.assert_called_once_with('home', 'goodpassword', 'wpa-psk', False)
        self.assertIn('Connected to home', self.screen())

    def test_open_network_asks_for_no_password(self):
        text = self.run_wifi('2')
        text.assert_not_called()
        self.connect.assert_called_once_with('cafe', None, None, False)

    def test_enterprise_network_is_refused(self):
        self.run_wifi('3')
        self.connect.assert_not_called()
        self.assertIn("can't be set up here", self.screen())

    def test_cancelling_the_list(self):
        self.run_wifi(None)
        self.connect.assert_not_called()
        self.assertIn('Wi-Fi not changed', self.screen())

    def test_cancelling_the_password(self):
        self.run_wifi('1', None)
        self.connect.assert_not_called()
        self.assertIn('Wi-Fi not changed', self.screen())

    def test_short_long_and_spaced_passwords_are_asked_again(self):
        text = self.run_wifi('1', 'short', 'x' * 64, ' leading space', 'trailing space ', 'goodpassword')
        self.assertEqual(text.call_count, 5)
        self.assertIn('8 to 63', text.call_args_list[1].args[0])
        self.assertIn('starts or ends with a space', text.call_args_list[3].args[0])
        self.connect.assert_called_once_with('home', 'goodpassword', 'wpa-psk', False)

    def test_length_counts_bytes(self):
        text = self.run_wifi('1', 'ä' * 32, 'ä' * 31)
        self.assertEqual(text.call_count, 2)

    def test_hidden_network_with_a_password(self):
        self.run_wifi('0', 'secretnet', 'goodpassword')
        self.connect.assert_called_once_with('secretnet', 'goodpassword', 'wpa-psk', True)

    def test_hidden_network_without_a_password(self):
        self.run_wifi('0', 'secretnet', '')
        self.connect.assert_called_once_with('secretnet', '', None, True)

    def test_list_only_accepts_the_shown_numbers(self):
        with mock.patch.object(self.menu, '_get_key', return_value=None) as key:
            self.menu._set_wifi()
        self.assertEqual(key.call_args.args[0], '0123')

    def test_at_most_nine_networks_are_listed(self):
        many = [{'ssid': f'net{n}', 'signal': 50, 'security': ''} for n in range(15)]
        with mock.patch('network_setup.scan', return_value=many), mock.patch.object(self.menu, '_get_key', return_value=None) as key:
            self.menu._set_wifi()
        self.assertEqual(key.call_args.args[0], '0123456789')

    def test_failure_is_shown(self):
        self.connect.return_value = (False, 'Could not connect to home.')
        self.run_wifi('1', 'goodpassword')
        self.assertIn('Could not connect to home', self.screen())

    def test_crash_never_shows_or_logs_the_password(self):
        self.connect.side_effect = RuntimeError('goodpassword leaked')
        with self.assertLogs('boot_menu', 'ERROR') as logs:
            self.run_wifi('1', 'goodpassword')
        self.assertNotIn('goodpassword', ''.join(logs.output))
        self.assertNotIn('goodpassword', self.screen())


class NextcloudSetup(MenuTestCase):
    def setUp(self):
        super().setUp()
        self.conf = self.tmp / 'nextcloud.conf'
        import nextcloud_sync
        self.nextcloud = nextcloud_sync
        for patcher in (mock.patch('time.sleep'),
                        mock.patch.object(nextcloud_sync, 'NEXTCLOUD_CONFIG_FILE', str(self.conf)),
                        mock.patch.object(nextcloud_sync, 'NEXTCLOUD_STATUS_FILE', str(self.tmp / 'status')),
                        mock.patch.object(nextcloud_sync, 'NEXTCLOUD_TRIGGER_FILE', str(self.tmp / 'trigger'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.plan = {'update': [], 'copy': ['new'], 'rename': [], 'delete': ['old-folder']}
        patcher = mock.patch.object(nextcloud_sync, 'preview', return_value=({'new': {}}, self.plan))
        self.preview = patcher.start()
        self.addCleanup(patcher.stop)

    def run_menu(self, keys, texts=()):
        with mock.patch.object(self.menu, '_get_key', side_effect=list(keys)) as key, \
                mock.patch.object(self.menu, '_get_text_input', side_effect=list(texts)) as text:
            self.menu._set_nextcloud()
        return key, text

    def saved(self):
        return self.nextcloud.load_config()

    def set_up(self, enabled=True):
        self.nextcloud.save_config(self.nextcloud.make_config(
            {'share_url': 'https://cloud.test/s/abc', 'enabled': enabled}))

    def test_share_link_setup(self):
        self.run_menu(['1', '1'], ['https://cloud.test/s/abc', 'sharepass', ''])
        config = self.saved()
        self.assertEqual((config['mode'], config['password'], config['interval'], config['enabled']),
                         ('share', 'sharepass', 15, True))
        self.assertTrue((self.tmp / 'trigger').exists())

    def test_account_setup(self):
        self.run_menu(['2', '1'], ['https://cloud.test', 'player', 'Videos/Looper', 'apppass', '30'])
        config = self.saved()
        self.assertEqual((config['mode'], config['username'], config['folder'], config['interval']),
                         ('account', 'player', 'Videos/Looper', 30))

    def test_password_entries_are_secret(self):
        _, text = self.run_menu(['1', '1'], ['https://cloud.test/s/abc', 'sharepass', ''])
        self.assertTrue(text.call_args_list[1].kwargs.get('secret'))
        _, text = self.run_menu(['2', '1'], ['https://cloud.test', 'player', '', 'apppass', ''])
        self.assertTrue(text.call_args_list[3].kwargs.get('secret'))

    def test_shows_removals_before_confirming(self):
        seen = []
        def get_key(valid):
            seen.append(self.screen())
            return next(keys)
        keys = iter(['1', None])
        with mock.patch.object(self.menu, '_get_key', get_key), \
                mock.patch.object(self.menu, '_get_text_input', side_effect=['https://cloud.test/s/abc', '', '']):
            self.menu._set_nextcloud()
        self.assertIn('REMOVE 1 local folder(s)', seen[-1])
        self.assertIn('old-folder', seen[-1])
        self.assertIn('USB video sync will be off', seen[-1])

    def test_not_saved_without_confirming(self):
        self.run_menu(['1', None], ['https://cloud.test/s/abc', '', ''])
        self.assertIsNone(self.saved())
        self.assertIn('Nothing was changed', self.screen())

    def test_failed_connection_saves_nothing(self):
        self.preview.side_effect = self.nextcloud.NextcloudError('The server refused the login')
        self.run_menu(['1'], ['https://cloud.test/s/abc', '', ''])
        self.assertIsNone(self.saved())
        self.assertIn('The server refused the login', self.screen())

    def test_bad_settings_are_explained(self):
        self.run_menu(['1'], ['http://cloud.test/s/abc', '', ''])
        self.assertIsNone(self.saved())
        self.assertIn('https://', self.screen())
        self.preview.assert_not_called()

    def test_cancelling_at_each_step(self):
        for texts in ([None], ['https://cloud.test/s/abc', None], ['https://cloud.test/s/abc', '', None]):
            self.run_menu(['1'], texts)
            self.assertIsNone(self.saved())

    def test_turning_off(self):
        self.set_up()
        self.run_menu(['3'])
        self.assertFalse(self.saved()['enabled'])

    def test_turning_on_tests_and_confirms(self):
        self.set_up(enabled=False)
        self.run_menu(['3', '1'])
        self.preview.assert_called_once()
        self.assertTrue(self.saved()['enabled'])

    def test_sync_now(self):
        self.set_up()
        self.run_menu(['4'])
        self.assertTrue((self.tmp / 'trigger').exists())

    def test_keys_offered_match_the_state(self):
        key, _ = self.run_menu([None])
        self.assertEqual(key.call_args.args[0], '12')
        self.set_up(enabled=False)
        key, _ = self.run_menu([None])
        self.assertEqual(key.call_args.args[0], '123')
        self.set_up()
        key, _ = self.run_menu([None])
        self.assertEqual(key.call_args.args[0], '1234')

    def test_crash_never_shows_or_logs_the_password(self):
        self.preview.side_effect = RuntimeError('sharepass leaked')
        with self.assertLogs('boot_menu', 'ERROR') as logs:
            self.run_menu(['1'], ['https://cloud.test/s/abc', 'sharepass', ''])
        self.assertNotIn('sharepass', ''.join(logs.output))
        self.assertNotIn('sharepass', self.screen())


class TimeSource(MenuTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def choose(self, key):
        with mock.patch.object(self.menu, '_get_key', return_value=key):
            self.menu._set_time_source()

    def test_switches_to_ntp(self):
        self.choose('1')
        self.time_sync.set_ntp.assert_called_once_with(True)
        self.assertIn('Time source: NTP', self.screen())

    def test_switches_to_rtc(self):
        self.time_sync.ntp_enabled.return_value = True
        self.choose('1')
        self.time_sync.set_ntp.assert_called_once_with(False)
        self.assertIn('Time source: RTC only', self.screen())

    def test_leaving_changes_nothing(self):
        self.choose(None)
        self.time_sync.set_ntp.assert_not_called()

    def test_failure_is_shown(self):
        self.time_sync.set_ntp.return_value = False
        self.choose('1')
        self.assertIn('Could not switch', self.screen())


class DemoMode(MenuTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('time.sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        # Never take the real lock, which would pause a running service
        patcher = mock.patch('time_entry.acquire_hold', return_value=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.player.start_video.return_value = True

    def test_plays_each_folder_for_a_minute_with_a_pause_between(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}, folder_name(2): {'b.mp4': ''}})
        self.menu.run_demo_mode()
        calls = self.player.start_video.call_args_list
        self.assertEqual([c.args[1].name for c in calls], [folder_name(1), folder_name(2)])
        self.assertTrue(all(c.kwargs == {'duration': 60, 'ignore_hold': True} for c in calls))
        self.assertEqual(self.sleep.call_args_list.count(mock.call(30)), 1)
        self.player.wake_display.assert_called_once()

    def test_waits_for_the_service_vlc_before_playing(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        order = []
        self.player.wait_for_vlc_to_exit.side_effect = lambda: order.append('wait')
        self.player.start_video.side_effect = lambda *a, **k: order.append('start') or True
        self.menu.run_demo_mode()
        self.assertEqual(order, ['wait', 'start'])

    def test_hold_lasts_for_the_whole_demo(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        hold = mock.Mock()
        order = []
        hold.close.side_effect = lambda: order.append('released')
        self.player.start_video.side_effect = lambda *a, **k: order.append('play') or True
        self.player.stop_video.side_effect = lambda **k: order.append('stop')
        with mock.patch('time_entry.acquire_hold', return_value=hold):
            self.menu.run_demo_mode()
        self.assertEqual(order[0], 'play')
        self.assertEqual(order[-2:], ['stop', 'released'])

    def test_leaves_the_display_to_the_service(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        self.menu.run_demo_mode()
        for call in self.player.stop_video.call_args_list:
            self.assertEqual(call, mock.call(standby_hdmi=False))

    def test_projector_goes_off_after_the_demo_if_nothing_is_scheduled(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        with mock.patch('scheduler.find_active_folder', return_value=None):
            self.menu.run_demo_mode()
        self.player.stop_projector.assert_called_once()
        self.player.release_projector.assert_not_called()

    def test_projector_stays_on_after_the_demo_if_something_is_scheduled(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        with mock.patch('scheduler.find_active_folder', return_value=(self.tmp, [])):
            self.menu.run_demo_mode()
        self.player.release_projector.assert_called_once()
        self.player.stop_projector.assert_not_called()

    def test_hold_released_if_the_demo_fails(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}})
        hold = mock.Mock()
        self.player.start_video.side_effect = RuntimeError('boom')
        with mock.patch('time_entry.acquire_hold', return_value=hold), self.assertLogs('boot_menu', 'ERROR'):
            self.menu.run_demo_mode()
        hold.close.assert_called_once()
        self.assertIn('Error in demo mode', self.screen())

    def test_nothing_to_play(self):
        self.menu.run_demo_mode()
        self.player.start_video.assert_not_called()
        self.assertIn('No valid video folders', self.screen())
