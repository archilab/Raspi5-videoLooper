#!/usr/bin/env python3
"""
Switches the HDMI signal on and off, using the kernel's framebuffer blanking.
With no signal, most displays go to sleep by themselves.

The video-looper service gives the looper user write access to the blank file when it
starts. VLC has to have exited first: the kernel refuses while VLC is using the display.
"""

import logging
import os

BLANK_FILE = '/sys/class/graphics/fb0/blank'
FB_BLANK_UNBLANK = 0
FB_BLANK_POWERDOWN = 4

STATE_STANDBY = 0
STATE_ON = 1


class HDMIController:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.last_state = None  # Last state successfully set; None until the first change

    def _write_blank(self, value):
        """Write to the kernel's blank file, returning True if it worked"""
        try:
            with open(BLANK_FILE, 'w') as f:
                f.write(str(value))
            return True
        except OSError as e:
            self.logger.warning(f"Could not switch the HDMI signal: {e}")
            return False

    def set_hdmi_power(self, state):
        """
        Switch the HDMI signal, if it differs from the last state set.
        A failure isn't remembered, so calling again retries it.
        Args:
            state: STATE_STANDBY or STATE_ON
        Returns:
            bool: True if the signal is in this state, False otherwise
        """
        if state == self.last_state:
            return True

        value = FB_BLANK_UNBLANK if state == STATE_ON else FB_BLANK_POWERDOWN
        if not self._write_blank(value):
            return False
        self.last_state = state
        return True

    def wake_hdmi(self):
        """Switch the HDMI signal on"""
        return self.set_hdmi_power(STATE_ON)

    def standby_hdmi(self):
        """Switch the HDMI signal off"""
        return self.set_hdmi_power(STATE_STANDBY)

    def is_available(self):
        """Check if the HDMI signal can be switched"""
        return os.access(BLANK_FILE, os.W_OK)
