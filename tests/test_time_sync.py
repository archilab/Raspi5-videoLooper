import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import time_sync

LOAD_COMMAND = ['/x/hwclock', '--hctosys', '--noadjfile', '--utc']
WRITE_COMMAND = ['/x/hwclock', '--systohc', '--noadjfile', '--utc']


class TimeSyncTestCase(unittest.TestCase):
    """The clock itself is never touched: hwclock and settimeofday are always faked"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        epoch_file = Path(tmp.name) / 'since_epoch'
        epoch_file.write_text('1793905000\n')
        for patcher in (mock.patch('time.sleep'), mock.patch.object(time_sync, 'RTC_EPOCH_FILE', str(epoch_file))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.commands = []

    def manager(self, returncodes=(), set_error=None):
        """A manager whose hwclock runs return these codes and whose clock setter records calls"""
        codes = iter(returncodes)

        def run(cmd, **kwargs):
            self.commands.append(cmd)
            return SimpleNamespace(returncode=next(codes), stdout='', stderr='hwclock says no')

        patcher = mock.patch.object(time_sync.subprocess, 'run', run)
        patcher.start()
        self.addCleanup(patcher.stop)
        manager = time_sync.TimeSyncManager()
        manager.hwclock_cmd = '/x/hwclock'
        manager._set_system_time = mock.Mock(return_value=set_error)
        return manager


class LoadFromRtc(TimeSyncTestCase):
    def test_uses_hwclock(self):
        manager = self.manager([0])
        self.assertTrue(manager.sync_time())
        self.assertEqual(self.commands, [LOAD_COMMAND])
        manager._set_system_time.assert_not_called()

    def test_falls_back_to_the_rtc_file(self):
        manager = self.manager([1])
        self.assertTrue(manager.sync_time())
        manager._set_system_time.assert_called_once_with(1793905000)

    def test_retries_then_reports_both_errors(self):
        manager = self.manager([1, 1, 1], set_error='Operation not permitted')
        with self.assertLogs('time_sync', logging.ERROR) as logs:
            self.assertFalse(manager.sync_time())
        self.assertEqual(self.commands, [LOAD_COMMAND] * 3)
        self.assertIn('hwclock says no', logs.output[0])
        self.assertIn('Operation not permitted', logs.output[0])

    def test_never_runs_anything_but_hwclock(self):
        manager = self.manager([1, 1, 1], set_error='no')
        with self.assertLogs('time_sync', logging.ERROR):
            manager.sync_time()
        self.assertTrue(all(cmd[0] == '/x/hwclock' for cmd in self.commands))


class SetManually(TimeSyncTestCase):
    def test_sets_system_clock_and_rtc(self):
        manager = self.manager([0])
        self.assertTrue(manager.set_time_manually('2026-11-05 12:00:00'))
        self.assertEqual(self.commands, [WRITE_COMMAND])
        manager._set_system_time.assert_called_once()

    def test_rtc_failure_is_reported(self):
        manager = self.manager([1])
        with self.assertLogs('time_sync', logging.ERROR) as logs:
            self.assertFalse(manager.set_time_manually('2026-11-05 12:00:00'))
        self.assertIn('write system time to RTC', logs.output[0])

    def test_system_clock_failure_stops_before_the_rtc(self):
        manager = self.manager([], set_error='Operation not permitted')
        with self.assertLogs('time_sync', logging.ERROR):
            self.assertFalse(manager.set_time_manually('2026-11-05 12:00:00'))
        self.assertEqual(self.commands, [])

    def test_bad_input_is_refused(self):
        manager = self.manager([])
        with self.assertLogs('time_sync', logging.ERROR):
            self.assertFalse(manager.set_time_manually('garbage'))
        manager._set_system_time.assert_not_called()


class LowLevel(unittest.TestCase):
    def test_settimeofday_values_and_error(self):
        libc = mock.Mock()
        libc.settimeofday.return_value = -1
        with mock.patch.object(time_sync.ctypes, 'CDLL', return_value=libc), \
                mock.patch.object(time_sync.ctypes, 'get_errno', return_value=1):
            error = time_sync.TimeSyncManager()._set_system_time(1793905000.5)
        self.assertEqual(error, 'Operation not permitted')
        timeval = libc.settimeofday.call_args.args[0]._obj
        self.assertEqual((timeval.tv_sec, timeval.tv_usec), (1793905000, 500000))

    def test_missing_hwclock_is_reported(self):
        def missing(cmd, **kwargs):
            raise FileNotFoundError('gone')

        with mock.patch.object(time_sync.subprocess, 'run', missing):
            manager = time_sync.TimeSyncManager()
            manager.hwclock_cmd = '/x/hwclock'
            with self.assertLogs('time_sync', logging.ERROR):
                self.assertFalse(manager.write_system_time_to_rtc())

    def test_timeout_is_reported(self):
        def slow(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        with mock.patch.object(time_sync.subprocess, 'run', slow):
            manager = time_sync.TimeSyncManager()
            manager.hwclock_cmd = '/x/hwclock'
            self.assertIn('timed out', manager._run_hwclock('--hctosys'))
