import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hdmi_controller
import projector_controller
from tests.helpers import FakeCec, make_hdmi


class HdmiController(unittest.TestCase):
    def setUp(self):
        self.cec = FakeCec()
        for patcher in (mock.patch.object(hdmi_controller.subprocess, 'run', self.cec), mock.patch('time.sleep')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_command_per_change(self):
        hdmi = make_hdmi()
        self.assertIsNone(hdmi.last_state)
        for _ in range(5):
            self.assertTrue(hdmi.wake_hdmi())
        self.assertEqual(self.cec.sent, ['on 0'])
        hdmi.standby_hdmi()
        hdmi.standby_hdmi()
        hdmi.wake_hdmi()
        self.assertEqual(self.cec.sent, ['on 0', 'standby 0', 'on 0'])

    def test_first_command_is_always_sent(self):
        make_hdmi().standby_hdmi()
        self.assertEqual(self.cec.sent, ['standby 0'])

    def test_failed_command_is_retried_until_it_works(self):
        hdmi = make_hdmi()
        hdmi.wake_hdmi()
        self.cec.sent.clear()
        self.cec.returncode = 1
        self.assertFalse(hdmi.standby_hdmi())
        self.assertFalse(hdmi.standby_hdmi())
        self.assertEqual(hdmi.last_state, hdmi_controller.STATE_ON)
        self.cec.returncode = 0
        self.assertTrue(hdmi.standby_hdmi())
        self.assertTrue(hdmi.standby_hdmi())
        self.assertEqual(self.cec.sent, ['standby 0'] * 3)

    def test_runs_directly_without_a_shell(self):
        with mock.patch.object(hdmi_controller.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            make_hdmi().wake_hdmi()
        self.assertEqual(run.call_args.args[0], ['/x/cec-client', '-s', '-d', '1'])
        self.assertEqual(run.call_args.kwargs['input'], 'on 0\n')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_timeout_is_a_failure(self):
        def slow(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        with mock.patch.object(hdmi_controller.subprocess, 'run', slow):
            self.assertFalse(make_hdmi().wake_hdmi())

    def test_without_cec_client(self):
        hdmi = make_hdmi()
        hdmi.cec_client_path = None
        self.assertFalse(hdmi.is_available())
        self.assertFalse(hdmi.wake_hdmi())
        self.assertEqual(self.cec.sent, [])


class ProjectorErrors(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.projector = projector_controller.ProjectorController()

    def test_bad_json_config(self):
        bad = self.tmp / 'bad.conf'
        bad.write_text('{not json')
        self.assertFalse(self.projector.load_config_from_file(str(bad)))

    def test_key_value_config(self):
        config = self.tmp / 'projector.txt'
        config.write_text('# comment\nenable_projector=true\nbaud_rate=9600\nstart_command=PWR ON\ndelay=1.5\n')
        self.assertTrue(self.projector.load_config_from_file(str(config)))
        self.assertEqual(self.projector.config, {'enable_projector': True, 'baud_rate': 9600,
                                                 'start_command': 'PWR ON', 'delay': 1.5})

    def test_missing_port_and_bad_baud_rate(self):
        self.projector.config = {'enable_projector': True, 'serial_port': str(self.tmp / 'nope'),
                                 'configure_stty': False}
        self.assertFalse(self.projector.connect())
        self.projector.config['baud_rate'] = 'fast'
        self.assertFalse(self.projector.connect())

    def test_disabled_projector_does_nothing(self):
        self.projector.config = {'enable_projector': False}
        self.assertTrue(self.projector.connect())
        self.assertTrue(self.projector.start_projector())
        self.assertFalse(self.projector.is_connected)
