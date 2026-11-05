#!/usr/bin/env python3
"""
HDMI Control Module using CEC (Consumer Electronics Control)
Handles HDMI display power management using cec-client from cec-utils

Each cec-client run takes about 3 seconds, and displays can't be relied on to report
their power state, so this remembers the last command and only sends changes.
"""

import subprocess
import logging
import shutil
import time

STATE_STANDBY = 0
STATE_ON = 1


class HDMIController:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.cec_client_path = shutil.which('cec-client')
        self.last_state = None  # Last state successfully sent; None until the first command

    def _send_cec_command(self, command):
        """
        Send a CEC command to control HDMI display
        Args:
            command: CEC command string (e.g., "standby 0", "on 0")
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.cec_client_path:
            return False

        try:
            result = subprocess.run(
                [self.cec_client_path, '-s', '-d', '1'],
                input=f"{command}\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                text=True
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def set_hdmi_power(self, state):
        """
        Set HDMI display power state using CEC, if it differs from the last one sent.
        A failed command isn't remembered, so calling again retries it.
        Args:
            state: STATE_STANDBY or STATE_ON
        Returns:
            bool: True if the display was told to be in this state, False otherwise
        """
        if state == self.last_state:
            return True

        if not self.cec_client_path:
            self.logger.warning("cec-client not available, cannot control HDMI")
            return False

        command = "on 0" if state == STATE_ON else "standby 0"
        if not self._send_cec_command(command):
            return False
        self.last_state = state
        time.sleep(1)
        return True

    def wake_hdmi(self):
        """Wake HDMI display (set to active)"""
        return self.set_hdmi_power(STATE_ON)

    def standby_hdmi(self):
        """Put HDMI display in standby (set to off)"""
        return self.set_hdmi_power(STATE_STANDBY)

    def is_available(self):
        """Check if HDMI control is available"""
        return self.cec_client_path is not None
