import logging
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
import time_entry
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
        self.menu = boot_menu.BootMenu(self.tmp / 'videos', self.player)

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
                         '\n\nSelect an option:\n\n  1. Start Demo Mode\n  2. Set RTC Time\n\n'
                         '  Press 1, 2, or Enter to continue...\n\n  Auto-continuing in 5 second(s)...\n\n')

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


class MenuKeys(MenuTestCase):
    def press(self, *keys):
        with mock.patch('time.sleep'), mock.patch.object(self.menu, '_setup_terminal_input'), \
                mock.patch.object(self.menu, '_restore_terminal_input'), \
                mock.patch.object(self.menu, 'get_char_blocking', side_effect=list(keys)), \
                mock.patch.object(self.menu, 'handle_manual_time_setting') as set_time:
            return self.menu.display_boot_menu(), set_time

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

    def test_timeout_cancels(self):
        self.assertIsNone(self.menu._get_numeric_input('P', 1, 12, timeout=0.2))


class DemoMode(MenuTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('time.sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self.player.start_video.return_value = True

    def test_plays_each_folder_for_a_minute_with_a_pause_between(self):
        make_tree(self.tmp / 'videos', {folder_name(1): {'a.mp4': ''}, folder_name(2): {'b.mp4': ''}})
        self.menu.run_demo_mode()
        calls = self.player.start_video.call_args_list
        self.assertEqual([c.args[1].name for c in calls], [folder_name(1), folder_name(2)])
        self.assertTrue(all(c.kwargs == {'duration': 60} for c in calls))
        self.assertEqual(self.sleep.call_args_list.count(mock.call(30)), 1)
        self.player.wake_display.assert_called_once()
        self.assertEqual(self.player.stop_video.call_args_list[-1], mock.call(standby_hdmi=True))

    def test_nothing_to_play(self):
        self.menu.run_demo_mode()
        self.player.start_video.assert_not_called()
        self.assertIn('No valid video folders', self.screen())
