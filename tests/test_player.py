import tempfile
import unittest
from pathlib import Path
from unittest import mock

import player
from tests.helpers import FakeDisplay, FakeProcess, FakeProjector, make_hdmi

LOOP_COMMAND = ['cvlc', '--intf', 'dummy', '--fullscreen', '--loop', '--no-osd', '--no-audio', '--quiet',
                'a.mp4', 'b.mp4']
DEMO_COMMAND = ['cvlc', '--intf', 'dummy', '--fullscreen', '--run-time', '60', '--no-osd', '--no-audio', '--quiet',
                'a.mp4']


class PlayerTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.display = FakeDisplay()
        self.commands = []

        def popen(cmd, **kwargs):
            self.commands.append(cmd)
            return FakeProcess()

        for patcher in (mock.patch.object(player.subprocess, 'Popen', popen),
                        mock.patch('time.sleep'),
                        mock.patch('time_entry.is_active', return_value=False),
                        mock.patch.object(player.Player, 'clear_display')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.projector = FakeProjector()
        self.player = player.Player(make_hdmi(self.display), self.projector)

    def enable_projector(self):
        (self.folder / 'projector.txt').write_text('enable_projector=true')


class Starting(PlayerTestCase):
    def test_vlc_command_for_looping(self):
        self.assertTrue(self.player.start_video(['a.mp4', 'b.mp4'], self.folder))
        self.assertEqual(self.commands, [LOOP_COMMAND])
        self.assertTrue(self.player.is_playing())
        self.assertEqual(self.player.current_folder, self.folder)

    def test_vlc_command_for_demo(self):
        self.assertTrue(self.player.start_video(['a.mp4'], self.folder, duration=60))
        self.assertEqual(self.commands, [DEMO_COMMAND])

    def test_no_videos(self):
        self.assertFalse(self.player.start_video([], self.folder))
        self.assertEqual(self.commands, [])

    def test_vlc_missing(self):
        with mock.patch.object(player.subprocess, 'Popen', side_effect=FileNotFoundError('cvlc')), \
                self.assertLogs('player', 'ERROR'):
            self.assertFalse(self.player.start_video(['a.mp4'], self.folder))
        self.assertFalse(self.player.is_playing())

    def test_time_entry_stops_the_start(self):
        with mock.patch('time_entry.is_active', return_value=True):
            self.assertFalse(self.player.start_video(['a.mp4'], self.folder))
        self.assertEqual(self.commands, [])

    def test_demo_can_start_during_its_own_hold(self):
        with mock.patch('time_entry.is_active', return_value=True):
            self.assertTrue(self.player.start_video(['a.mp4'], self.folder, duration=60, ignore_hold=True))

    def test_display_woken_once(self):
        self.player.start_video(['a.mp4'], self.folder)
        self.player.start_video(['a.mp4'], self.folder)
        self.assertEqual(self.display.sent, ['on'])

    def test_projector_started_once_when_enabled(self):
        self.enable_projector()
        self.player.start_video(['a.mp4'], self.folder)
        self.assertEqual(self.projector.calls, ['connect', 'start'])

    def test_projector_failure_does_not_stop_the_video(self):
        self.enable_projector()
        with mock.patch.object(self.projector, 'connect', return_value=False), self.assertLogs('player', 'ERROR'):
            self.assertTrue(self.player.start_video(['a.mp4'], self.folder))

    def test_video_start_delay(self):
        (self.folder / 'projector.txt').write_text('disabled')
        self.projector.load_config_from_file = lambda path: setattr(self.projector, 'config', {'video_start_delay': '5'})
        import time
        self.player.start_video(['a.mp4'], self.folder)
        self.assertIn(mock.call(5), time.sleep.call_args_list)


class WaitingForVlc(PlayerTestCase):
    def pgrep(self, *returncodes):
        codes = iter(returncodes)
        return mock.patch.object(player.subprocess, 'run',
                                 side_effect=lambda *a, **k: mock.Mock(returncode=next(codes)))

    def test_returns_when_no_vlc_is_left(self):
        with self.pgrep(0, 0, 1) as run:
            self.assertTrue(self.player.wait_for_vlc_to_exit())
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args.args[0], ['pgrep', '-x', 'vlc'])

    def test_gives_up_after_the_timeout(self):
        with mock.patch.object(player.subprocess, 'run', return_value=mock.Mock(returncode=0)), \
                self.assertLogs('player', 'WARNING'):
            self.assertFalse(self.player.wait_for_vlc_to_exit(timeout=0.01))

    def test_missing_pgrep_does_not_stop_the_demo(self):
        with mock.patch.object(player.subprocess, 'run', side_effect=FileNotFoundError('pgrep')):
            self.assertFalse(self.player.wait_for_vlc_to_exit())


class Stopping(PlayerTestCase):
    def test_stops_vlc_and_projector(self):
        self.enable_projector()
        self.player.start_video(['a.mp4'], self.folder)
        process = self.player.current_process
        self.player.stop_video()
        self.assertFalse(process.alive)
        self.assertIsNone(self.player.current_process)
        self.assertIsNone(self.player.current_folder)
        self.assertEqual(self.projector.calls, ['connect', 'start', 'stop', 'disconnect'])
        self.assertEqual(self.display.sent, ['on'])

    def test_standby(self):
        self.player.start_video(['a.mp4'], self.folder)
        self.player.stop_video(standby_hdmi=True)
        self.assertEqual(self.display.sent, ['on', 'off'])
        self.player.clear_display.assert_called_once()

    def test_stuck_vlc_is_killed(self):
        self.player.current_process = process = FakeProcess(stuck=True)
        self.player.stop_video()
        self.assertTrue(process.killed)

    def test_stopping_when_idle_is_harmless(self):
        self.player.stop_video()
        self.assertEqual(self.display.sent, [])
        self.assertEqual(self.projector.calls, [])

    def test_crashed_vlc_is_not_playing(self):
        self.player.start_video(['a.mp4'], self.folder)
        self.player.current_process.alive = False
        self.assertFalse(self.player.is_playing())
