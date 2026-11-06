import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import hdmi_controller
import player
import time_entry
import video_looper
from tests.helpers import FakeDisplay, FakeProcess, FakeProjector, make_hdmi

FOLDER_A = (Path('/nonexistent/A'), [Path('a.mp4')])
FOLDER_B = (Path('/nonexistent/B'), [Path('b.mp4')])


class MainLoopTestCase(unittest.TestCase):
    """The real loop and Player, with VLC, the display and the waits between passes faked"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.display = FakeDisplay()
        self.vlc = []
        self.active = None
        self.time_entry_active = False

        def popen(cmd, **kwargs):
            self.vlc.append(FakeProcess())
            self.commands.append(cmd[-1])
            return self.vlc[-1]

        self.commands = []
        for patcher in (mock.patch.object(player.subprocess, 'Popen', popen),
                        mock.patch.object(video_looper, 'BOOT_MENU_GRACE', 0),
                        mock.patch('time.sleep'),
                        mock.patch.object(player.Player, 'clear_display'),
                        mock.patch('scheduler.find_active_folder', side_effect=lambda path: self.active),
                        mock.patch('time_entry.is_active', side_effect=lambda: self.time_entry_active),
                        mock.patch.object(video_looper, 'CHECK_INTERVAL', 1)):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.looper = video_looper.VideoLooper.__new__(video_looper.VideoLooper)
        self.looper.logger = logging.getLogger('looper-test')
        self.looper.videos_path = Path(self.tmp)
        self.looper.running = True
        self.looper.hdmi = make_hdmi(self.display)
        self.looper.projector = FakeProjector()
        self.looper.player = player.Player(self.looper.hdmi, self.looper.projector)
        self.looper.usb_sync = SimpleNamespace(sync_on_boot=lambda: None)
        self.looper.time_sync = mock.Mock()

    def run_passes(self, *steps):
        """Run the loop, doing one step after each pass: a callable, then checks, or None"""
        steps = iter(steps)
        self.clock = 0

        def after_pass(_seconds):
            try:
                step = next(steps)
            except StopIteration:
                raise KeyboardInterrupt
            if step:
                step()

        fake_time = SimpleNamespace(sleep=after_pass, monotonic=lambda: self.clock)
        with mock.patch.object(video_looper, 'time', fake_time):
            self.looper.run()

    def set_active(self, folder):
        self.active = folder


class Decisions(MainLoopTestCase):
    def test_starts_keeps_restarts_switches_and_stops(self):
        self.active = FOLDER_A
        counts = []
        note = lambda: counts.append(len(self.vlc))
        self.run_passes(
            lambda: (note(),),                                    # first pass started A
            lambda: (note(), self.vlc[-1].terminate()),           # still one; now VLC dies
            lambda: (note(), self.set_active(FOLDER_B)),          # restarted; folder changes
            lambda: (note(), self.set_active(None)),              # switched; schedule ends
            note,                                                 # stopped, nothing new
        )
        self.assertEqual(counts, [1, 1, 2, 3, 3])
        self.assertEqual(self.commands, ['a.mp4', 'a.mp4', 'b.mp4'])
        self.assertFalse(self.vlc[-1].alive)

    def test_failed_start_is_retried(self):
        self.active = FOLDER_A
        with mock.patch.object(player.subprocess, 'Popen', side_effect=OSError('no vlc')), \
                self.assertLogs('player', 'ERROR'):
            self.run_passes()
        self.run_passes(None)
        self.assertEqual(len(self.vlc), 1)

    def test_usb_sync_failure_does_not_stop_the_player(self):
        self.active = FOLDER_A
        self.looper.usb_sync = SimpleNamespace(sync_on_boot=mock.Mock(side_effect=RuntimeError('bad drive')))
        with self.assertLogs('looper-test', 'ERROR') as logs:
            self.run_passes(None)
        self.assertIn('bad drive', logs.output[0])
        self.assertEqual(len(self.vlc), 1)

    def test_loads_rtc_at_startup(self):
        self.run_passes()
        self.looper.time_sync.sync_time.assert_called_once()

    def test_error_in_a_pass_is_logged_and_the_loop_continues(self):
        results = [RuntimeError('oops'), None]
        with mock.patch('scheduler.find_active_folder', side_effect=results + [None] * 5), \
                self.assertLogs('looper-test', 'ERROR') as logs:
            self.run_passes(None, None)
        self.assertIn('oops', logs.output[0])


class DisplaySignal(MainLoopTestCase):
    def test_switches_only_on_changes(self):
        idle = [None] * 99
        playing = [None] * 99
        self.run_passes(
            *idle,
            lambda: self.set_active(FOLDER_A), *playing,
            lambda: self.vlc[-1].terminate(), None,               # crash: signal stays on
            lambda: self.set_active(None), *idle,
            lambda: self.set_active(FOLDER_A), *playing,
        )
        self.assertEqual(self.display.sent, ['off', 'on', 'off', 'on'])
        self.assertEqual(len(self.vlc), 3)

    def test_failed_wake_is_retried_while_playing(self):
        self.active = FOLDER_A
        self.display.fail = True
        def recover():
            self.display.fail = False
        self.run_passes(None, recover, None, None)
        self.assertEqual(self.display.sent, ['on', 'on', 'on'])

    def test_stays_on_for_the_boot_menu_after_starting(self):
        def advance(seconds):
            def step():
                self.clock = seconds
            return step

        seen = []
        note = lambda: seen.append(list(self.display.sent))
        with mock.patch.object(video_looper, 'BOOT_MENU_GRACE', 60):
            self.run_passes(advance(30), note, advance(59), note, advance(60), None, note)
        self.assertEqual(seen, [[], [], ['off']])

    def test_scheduled_video_ignores_the_grace_period(self):
        self.active = FOLDER_A
        with mock.patch.object(video_looper, 'BOOT_MENU_GRACE', 60):
            self.run_passes(None)
        self.assertEqual(self.display.sent, ['on'])

    def test_signal_goes_off_when_the_schedule_ends(self):
        self.active = FOLDER_A
        seen = []
        self.run_passes(lambda: self.set_active(None), lambda: seen.append(list(self.display.sent)))
        self.assertEqual(seen, [['on', 'off']])

    def test_signal_is_on_after_shutting_down(self):
        self.run_passes(None)
        self.assertEqual(self.display.sent, ['off', 'on'])

    def test_signal_handler_stops_video_and_leaves_signal_on(self):
        self.active = FOLDER_A
        self.run_passes(None)
        self.looper.player.current_process = process = FakeProcess()
        self.looper.hdmi.standby_hdmi()
        self.display.sent.clear()
        with self.assertRaises(SystemExit):
            self.looper.signal_handler(15, None)
        self.assertFalse(process.alive)
        self.assertEqual(self.display.sent, ['on'])

    def test_warns_if_the_signal_cannot_be_switched(self):
        self.looper.hdmi.is_available = lambda: False
        with self.assertLogs('looper-test', 'WARNING') as logs:
            self.run_passes(None)
        self.assertIn("HDMI signal can't be switched", logs.output[0])
        self.assertEqual(self.display.sent, [])


class UpdatedVideos(MainLoopTestCase):
    def test_changed_files_restart_the_video(self):
        self.active = FOLDER_A
        signatures = iter([['one'], ['one'], ['two'], ['two']])
        with mock.patch('scheduler.video_signature', side_effect=lambda files: next(signatures)):
            self.run_passes(None, None, None)
        self.assertEqual(len(self.vlc), 2)
        self.assertFalse(self.vlc[0].alive)

    def test_unchanged_files_keep_playing(self):
        self.active = FOLDER_A
        self.run_passes(None, None, None)
        self.assertEqual(len(self.vlc), 1)

    def test_projector_stays_on_when_videos_change(self):
        folder = Path(self.tmp) / 'with-projector'
        folder.mkdir()
        (folder / 'projector.txt').write_text('enable_projector=true')
        self.active = (folder, [Path('a.mp4')])
        seen = []
        signatures = iter([['one'], ['two'], ['two'], ['two']])
        with mock.patch('scheduler.video_signature', side_effect=lambda files: next(signatures)):
            self.run_passes(None, lambda: seen.append(list(self.looper.projector.calls)))
        self.assertEqual(seen, [['connect', 'start']])


class RtcUpdates(MainLoopTestCase):
    def test_updates_at_startup_then_every_interval(self):
        update = self.looper.time_sync.update_rtc_from_ntp
        counts = []
        def advance(seconds):
            def step():
                self.clock = seconds
            return step
        self.run_passes(advance(300), lambda: counts.append(update.call_count),
                        advance(600), None, lambda: counts.append(update.call_count))
        self.assertEqual(counts, [1, 2])

    def test_not_during_a_hold(self):
        self.time_entry_active = True
        self.run_passes(None, None)
        self.looper.time_sync.update_rtc_from_ntp.assert_not_called()


class ProjectorPower(MainLoopTestCase):
    def setUp(self):
        super().setUp()
        self.folder = Path(self.tmp) / 'with-projector'
        self.folder.mkdir()
        (self.folder / 'projector.txt').write_text('enable_projector=true')
        self.active = (self.folder, [Path('a.mp4')])
        self.calls = self.looper.projector.calls

    def test_stays_on_through_a_vlc_crash(self):
        seen = []
        self.run_passes(lambda: self.vlc[-1].terminate(), None, lambda: seen.append(list(self.calls)))
        self.assertEqual(seen, [['connect', 'start']])
        self.assertEqual(len(self.vlc), 2)

    def test_stops_when_nothing_is_scheduled(self):
        seen = []
        self.run_passes(lambda: self.set_active(None), lambda: seen.append(list(self.calls)))
        self.assertEqual(seen, [['connect', 'start', 'stop', 'disconnect']])

    def test_stays_on_through_time_entry(self):
        seen = []
        def hold():
            self.time_entry_active = True
        def release():
            self.time_entry_active = False
        self.run_passes(hold, None, lambda: seen.append(list(self.calls)), release, None,
                        lambda: seen.append(list(self.calls)))
        self.assertEqual(seen, [['connect', 'start'], ['connect', 'start']])

    def test_stops_if_the_schedule_ended_during_a_hold(self):
        seen = []
        def hold():
            self.time_entry_active = True
        def release():
            self.time_entry_active = False
            self.active = None
        self.run_passes(hold, None, release, None, lambda: seen.append(list(self.calls)))
        self.assertEqual(seen, [['connect', 'start', 'stop', 'disconnect']])

    def test_stops_when_the_service_stops(self):
        self.run_passes(None)
        self.assertEqual(self.calls[:3], ['connect', 'start', 'stop'])

    def test_grace_period_does_not_delay_stopping_the_projector(self):
        seen = []
        with mock.patch.object(video_looper, 'BOOT_MENU_GRACE', 60):
            self.run_passes(lambda: self.set_active(None), lambda: seen.append(list(self.calls)))
        self.assertIn('stop', seen[0])


class TimeEntryHold(MainLoopTestCase):
    def setUp(self):
        super().setUp()
        for name in ('TIME_SET_REQUEST_FILE', 'TIME_SET_RESULT_FILE'):
            patcher = mock.patch.object(time_entry, name, os.path.join(self.tmp, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def hold(self):
        self.time_entry_active = True

    def release(self):
        self.time_entry_active = False

    def test_stops_video_keeps_display_awake_and_resumes(self):
        self.active = FOLDER_A
        seen = []
        self.run_passes(
            self.hold,                                            # playing, then the menu takes the hold
            None,
            lambda: seen.append((self.looper.player.is_playing(), len(self.vlc))),
            self.release,
            None,
        )
        self.assertEqual(seen, [(False, 1)])
        self.assertEqual(len(self.vlc), 2)
        self.assertEqual(self.display.sent, ['on'])

    def test_wakes_display_for_the_menu_when_idle(self):
        seen = []
        self.run_passes(self.hold, lambda: seen.append(list(self.display.sent)))
        self.assertEqual(seen, [['off', 'on']])

    def test_display_goes_back_to_standby_after_the_hold(self):
        seen = []
        self.run_passes(self.hold, None, self.release, None, lambda: seen.append(self.looper.hdmi.last_state))
        self.assertEqual(seen, [hdmi_controller.STATE_STANDBY])

    def test_processes_the_time_request_during_the_hold(self):
        self.looper.time_sync.set_time_manually.return_value = True

        def send_request():
            self.hold()
            with open(time_entry.TIME_SET_REQUEST_FILE, 'w') as f:
                f.write('2026-11-05 12:00:00')

        self.run_passes(send_request, None, self.release)
        self.looper.time_sync.set_time_manually.assert_called_once_with('2026-11-05 12:00:00')
        with open(time_entry.TIME_SET_RESULT_FILE) as f:
            self.assertEqual(f.read(), 'ok')
