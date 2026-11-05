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


class TimeSource(TimeSyncTestCase):
    def setUp(self):
        super().setUp()
        self.synced_file = Path(time_sync.RTC_EPOCH_FILE).with_name('synced')
        patcher = mock.patch.object(time_sync, 'NTP_SYNCED_FILE', str(self.synced_file))
        patcher.start()
        self.addCleanup(patcher.stop)

    def timedatectl(self, stdout='', returncode=0):
        def run(cmd, **kwargs):
            self.commands.append(cmd)
            return SimpleNamespace(returncode=returncode if cmd[0] == 'timedatectl' else 0, stdout=stdout, stderr='no')
        patcher = mock.patch.object(time_sync.subprocess, 'run', run)
        patcher.start()
        self.addCleanup(patcher.stop)
        manager = time_sync.TimeSyncManager()
        manager.hwclock_cmd = '/x/hwclock'
        return manager

    def test_reads_whether_ntp_is_on(self):
        self.assertTrue(self.timedatectl('yes\n').ntp_enabled())
        self.assertFalse(self.timedatectl('no\n').ntp_enabled())

    def test_switching(self):
        manager = self.timedatectl()
        self.assertTrue(manager.set_ntp(True))
        self.assertTrue(manager.set_ntp(False))
        self.assertEqual(self.commands, [['timedatectl', 'set-ntp', 'true'], ['timedatectl', 'set-ntp', 'false']])

    def test_failed_switch_is_reported(self):
        manager = self.timedatectl(returncode=1)
        with self.assertLogs('time_sync', logging.ERROR):
            self.assertFalse(manager.set_ntp(True))

    def test_missing_timedatectl_counts_as_off(self):
        with mock.patch.object(time_sync.subprocess, 'run', side_effect=FileNotFoundError('gone')), \
                self.assertLogs('time_sync', logging.ERROR):
            self.assertFalse(time_sync.TimeSyncManager().ntp_enabled())

    def test_synced_needs_ntp_on_and_the_file(self):
        manager = self.timedatectl('yes\n')
        self.assertFalse(manager.is_ntp_synced())
        self.synced_file.write_text('')
        self.assertTrue(manager.is_ntp_synced())
        self.assertFalse(self.timedatectl('no\n').is_ntp_synced())

    def test_no_timedatectl_call_before_the_first_sync(self):
        """This runs early in boot, when timedatectl can't answer yet"""
        manager = self.timedatectl('yes\n')
        manager.is_ntp_synced()
        self.assertEqual(self.commands, [])

    def test_rtc_is_updated_only_when_synced(self):
        manager = self.timedatectl('yes\n')
        manager.update_rtc_from_ntp()
        self.assertEqual(self.commands, [])
        self.synced_file.write_text('')
        manager.update_rtc_from_ntp()
        self.assertIn(WRITE_COMMAND, self.commands)

    def test_startup_keeps_ntp_time_over_the_rtc(self):
        self.synced_file.write_text('')
        manager = self.timedatectl('yes\n')
        self.assertTrue(manager.sync_time())
        self.assertNotIn(LOAD_COMMAND, self.commands)

    def test_startup_uses_the_rtc_otherwise(self):
        manager = self.timedatectl('yes\n')
        self.assertTrue(manager.sync_time())
        self.assertIn(LOAD_COMMAND, self.commands)

    def test_status_shows_the_source(self):
        self.assertEqual(self.timedatectl('yes\n').get_time_status()['mode'], 'NTP when internet is available')
        self.assertEqual(self.timedatectl('no\n').get_time_status()['mode'], 'RTC only')


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
