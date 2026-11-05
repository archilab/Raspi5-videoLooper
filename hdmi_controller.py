#!/usr/bin/env python3
"""
HDMI Control Module using CEC (Consumer Electronics Control)
Handles HDMI display power management using cec-client from cec-utils
"""

import subprocess
import logging
import shutil
import time

class HDMIController:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.cec_client_path = self._find_cec_client()
    
    def _find_cec_client(self):
        """Find cec-client executable"""
        # Check common locations
        common_paths = [
            '/usr/bin/cec-client',
            '/usr/local/bin/cec-client',
            shutil.which('cec-client')
        ]
        
        for path in common_paths:
            if path and shutil.which(path):
                return path
        
        return None
    
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
        Set HDMI display power state using CEC
        Args:
            state: 0 = standby/off, 1 = on/active
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.cec_client_path:
            self.logger.warning("cec-client not available, cannot control HDMI")
            return False
        
        if state not in [0, 1]:
            return False
        
        command = "on 0" if state == 1 else "standby 0"
        success = self._send_cec_command(command)
        if success:
            time.sleep(1)
        return success
    
    def get_hdmi_power(self):
        """Get current HDMI display power state"""
        if not self.cec_client_path:
            return None
        
        try:
            result = subprocess.run(
                [self.cec_client_path, '-s', '-d', '1'],
                input="tx 10:8F\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                text=True
            )
            if result.returncode == 0:
                output = result.stdout.strip().lower()
                return 1 if "ack" in output or "feature abort" not in output else 0
            return None
        except (OSError, subprocess.SubprocessError):
            return None
    
    def wake_hdmi(self):
        """Wake HDMI display (set to active)"""
        return self.set_hdmi_power(1)
    
    def standby_hdmi(self):
        """Put HDMI display in standby (set to off)"""
        return self.set_hdmi_power(0)
    
    def is_available(self):
        """Check if HDMI control is available"""
        return self.cec_client_path is not None
