import os
import pty
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hdmi_controller
import projector_controller


class HdmiController(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.blank = Path(tmp.name) / 'blank'
        self.blank.write_text('')
        patcher = mock.patch.object(hdmi_controller, 'BLANK_FILE', str(self.blank))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.writes = []
        self.hdmi = hdmi_controller.HDMIController()

    def test_writes_the_kernel_values(self):
        self.assertTrue(self.hdmi.standby_hdmi())
        self.assertEqual(self.blank.read_text(), '4')
        self.assertTrue(self.hdmi.wake_hdmi())
        self.assertEqual(self.blank.read_text(), '0')

    def test_first_change_is_always_written(self):
        self.assertIsNone(self.hdmi.last_state)
        self.hdmi.wake_hdmi()
        self.assertEqual(self.blank.read_text(), '0')

    def test_writes_only_on_changes(self):
        self.hdmi.wake_hdmi()
        self.blank.write_text('untouched')
        for _ in range(5):
            self.assertTrue(self.hdmi.wake_hdmi())
        self.assertEqual(self.blank.read_text(), 'untouched')
        self.hdmi.standby_hdmi()
        self.assertEqual(self.blank.read_text(), '4')

    def test_failed_change_is_retried_until_it_works(self):
        self.hdmi.wake_hdmi()
        working = self.blank
        with mock.patch.object(hdmi_controller, 'BLANK_FILE', str(working.parent / 'missing' / 'blank')), \
                self.assertLogs('hdmi_controller', 'WARNING'):
            self.assertFalse(self.hdmi.standby_hdmi())
            self.assertFalse(self.hdmi.standby_hdmi())
        self.assertEqual(self.hdmi.last_state, hdmi_controller.STATE_ON)
        self.assertTrue(self.hdmi.standby_hdmi())
        self.assertEqual(working.read_text(), '4')

    def test_availability_follows_write_access(self):
        self.assertTrue(self.hdmi.is_available())
        with mock.patch.object(hdmi_controller, 'BLANK_FILE', str(self.blank.parent / 'missing')):
            self.assertFalse(self.hdmi.is_available())


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

    def test_connection_test_opens_and_closes_the_port(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        self.projector.config = {'enable_projector': False, 'serial_port': os.ttyname(slave), 'configure_stty': False}
        self.assertTrue(self.projector.test_connection())
        self.assertFalse(self.projector.is_connected)
        self.assertFalse(self.projector.serial_connection.is_open)

    def test_connection_test_fails_for_a_missing_port(self):
        self.projector.config = {'serial_port': str(self.tmp / 'nope'), 'configure_stty': False}
        self.assertFalse(self.projector.test_connection())

    def test_disabled_projector_does_nothing(self):
        self.projector.config = {'enable_projector': False}
        self.assertTrue(self.projector.connect())
        self.assertTrue(self.projector.start_projector())
        self.assertFalse(self.projector.is_connected)
