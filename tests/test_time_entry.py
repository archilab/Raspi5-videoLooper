import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import time_entry
from tests.helpers import ROOT


class TimeEntryTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.lock = self.tmp / 'lock'
        self.request = self.tmp / 'request'
        self.result = self.tmp / 'result'
        for patcher in (mock.patch.object(time_entry, 'TIME_ENTRY_LOCK_FILE', str(self.lock)),
                        mock.patch.object(time_entry, 'TIME_SET_REQUEST_FILE', str(self.request)),
                        mock.patch.object(time_entry, 'TIME_SET_RESULT_FILE', str(self.result)),
                        mock.patch.object(time_entry, 'TIME_SET_TIMEOUT', 2)):
            patcher.start()
            self.addCleanup(patcher.stop)


class Hold(TimeEntryTestCase):
    def test_not_active_without_a_hold(self):
        self.assertFalse(time_entry.is_active())

    def test_active_until_released(self):
        hold = time_entry.acquire_hold()
        self.assertTrue(self._seen_by_another_process())
        hold.close()
        self.assertFalse(self._seen_by_another_process())

    def _seen_by_another_process(self):
        code = ("import sys, time_entry; time_entry.TIME_ENTRY_LOCK_FILE = sys.argv[1]; "
                "print(time_entry.is_active())")
        output = subprocess.check_output([sys.executable, '-c', code, str(self.lock)], cwd=ROOT, text=True)
        return output.strip() == 'True'

    def test_crashed_menu_leaves_no_hold(self):
        code = ("import sys, time, time_entry; time_entry.TIME_ENTRY_LOCK_FILE = sys.argv[1]; "
                "h = time_entry.acquire_hold(); print('held', flush=True); time.sleep(60)")
        process = subprocess.Popen([sys.executable, '-c', code, str(self.lock)], cwd=ROOT,
                                   stdout=subprocess.PIPE, text=True)
        self.addCleanup(process.stdout.close)
        self.assertEqual(process.stdout.readline().strip(), 'held')
        self.assertTrue(time_entry.is_active())
        os.kill(process.pid, signal.SIGKILL)
        process.wait()
        self.assertFalse(time_entry.is_active())

    def test_unusable_lock_file_is_harmless(self):
        with mock.patch.object(time_entry, 'TIME_ENTRY_LOCK_FILE', str(self.tmp / 'missing' / 'lock')), \
                self.assertLogs('time_entry', 'ERROR'):
            self.assertIsNone(time_entry.acquire_hold())
            self.assertFalse(time_entry.is_active())


class Handoff(TimeEntryTestCase):
    def serve(self, answer):
        """Answer requests from a background thread, as the service does"""
        calls = []
        done = threading.Event()

        def set_time(time_str):
            calls.append(time_str)
            return answer

        def loop():
            while not done.is_set():
                time_entry.process_request(set_time)
                time.sleep(0.02)

        thread = threading.Thread(target=loop)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(done.set)
        return calls

    def test_service_says_ok(self):
        calls = self.serve(True)
        self.assertTrue(time_entry.request_time_set('2026-11-05 12:00:00'))
        self.assertEqual(calls, ['2026-11-05 12:00:00'])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_service_says_failed(self):
        self.serve(False)
        self.assertFalse(time_entry.request_time_set('2026-11-05 12:00:00'))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_no_service_withdraws_the_request(self):
        with mock.patch.object(time_entry, 'TIME_SET_TIMEOUT', 0.3), self.assertLogs('time_entry', 'ERROR'):
            self.assertFalse(time_entry.request_time_set('2026-11-05 12:00:00'))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_stale_result_is_ignored(self):
        self.result.write_text('ok')
        with mock.patch.object(time_entry, 'TIME_SET_TIMEOUT', 0.3), self.assertLogs('time_entry', 'ERROR'):
            self.assertFalse(time_entry.request_time_set('2026-11-05 12:00:00'))

    def test_no_request_does_nothing(self):
        set_time = mock.Mock()
        time_entry.process_request(set_time)
        set_time.assert_not_called()

    def test_request_from_another_user_is_ignored(self):
        self.request.write_text('2026-11-05 12:00:00')
        set_time = mock.Mock()
        with mock.patch.object(time_entry.os, 'getuid', return_value=os.getuid() + 1):
            time_entry.process_request(set_time)
        set_time.assert_not_called()
