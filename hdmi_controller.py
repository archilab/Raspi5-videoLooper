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
    def __init__(self, log_file="/var/log/video_looper.log"):
        self.logger = logging.getLogger(__name__)
        self.log_file = log_file
        self.cec_client_path = self._find_cec_client()
        
        if not self.cec_client_path:
            self.logger.warning("cec-client not found. HDMI control will be disabled.")
        else:
            self.logger.info(f"HDMI controller initialized using {self.cec_client_path}")
    
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
            self.logger.warning("cec-client not available, cannot control HDMI")
            return False
        
        try:
            # cec-client sends commands to the default CEC adapter
            # Format: echo "<command>" | cec-client -s -d 1
            # -s = single command mode, -d 1 = device 1 (Raspberry Pi)
            # Commands: "standby 0" (TV address 0), "on 0" (TV address 0)
            cmd = ['sh', '-c', f'echo "{command}" | {self.cec_client_path} -s -d 1']
            
            self.logger.debug(f"Running CEC command: {command}")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                text=True
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                self.logger.debug(f"CEC command successful. Output: {output}")
                # Check for success indicators
                if "sending" in output.lower() or "command" in output.lower() or output == "":
                    return True
                return True
            else:
                error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
                self.logger.error(f"Failed to send CEC command. Return code: {result.returncode}")
                if error_msg:
                    self.logger.error(f"Error: {error_msg}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout while sending CEC command")
            return False
        except Exception as e:
            self.logger.error(f"Error sending CEC command: {e}")
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
        
        try:
            if state not in [0, 1]:
                self.logger.error(f"Invalid HDMI state: {state}. Must be 0 (off) or 1 (on)")
                return False
            
            if state == 1:
                # Wake up display: CEC command "on 0" (0 is TV address)
                command = "on 0"
                self.logger.info("Waking HDMI display...")
            else:
                # Put display in standby: CEC command "standby 0" (0 is TV address)
                command = "standby 0"
                self.logger.info("Putting HDMI display in standby...")
            
            # Send CEC command
            success = self._send_cec_command(command)
            
            if success:
                state_name = "on" if state == 1 else "standby"
                self.logger.info(f"HDMI display set to {state_name}")
                # Give display time to respond
                time.sleep(1)
                return True
            else:
                self.logger.error(f"Failed to set HDMI display to {'on' if state == 1 else 'standby'}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error setting HDMI power state: {e}")
            return False
    
    def get_hdmi_power(self):
        """
        Get current HDMI display power state using CEC
        Returns:
            int: 0 = off/standby, 1 = on, None if unavailable
        """
        if not self.cec_client_path:
            self.logger.warning("cec-client not available, cannot query HDMI state")
            return None
        
        try:
            # Query power status: CEC command "polling message"
            # This checks if the display responds
            cmd = ['sh', '-c', f'echo "tx 10:8F" | {self.cec_client_path} -s -d 1']
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                text=True
            )
            
            if result.returncode == 0:
                # If we get a response, display is likely on
                # CEC polling is tricky - simpler approach: try to ping the display
                output = result.stdout.strip().lower()
                if "ack" in output or "feature abort" not in output:
                    # Display responded - likely on
                    return 1
                else:
                    # Display didn't respond - likely off/standby
                    return 0
            else:
                self.logger.debug("Could not query HDMI power state via CEC")
                return None
                
        except subprocess.TimeoutExpired:
            self.logger.debug("Timeout while querying HDMI power state")
            return None
        except Exception as e:
            self.logger.debug(f"Error querying HDMI power state: {e}")
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

def main():
    """Test the HDMI controller"""
    import argparse
    
    parser = argparse.ArgumentParser(description='HDMI Controller using CEC')
    parser.add_argument('--status', action='store_true', help='Show HDMI power status')
    parser.add_argument('--on', action='store_true', help='Turn HDMI on')
    parser.add_argument('--off', action='store_true', help='Turn HDMI off')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    controller = HDMIController()
    
    if args.status:
        state = controller.get_hdmi_power()
        if state is not None:
            state_name = "on" if state == 1 else "standby"
            print(f"HDMI display is currently: {state_name} ({state})")
        else:
            print("HDMI status unavailable")
    
    elif args.on:
        if controller.wake_hdmi():
            print("✓ HDMI display turned on")
        else:
            print("✗ Failed to turn HDMI display on")
    
    elif args.off:
        if controller.standby_hdmi():
            print("✓ HDMI display turned off")
        else:
            print("✗ Failed to turn HDMI display off")
    
    else:
        print("HDMI Controller using CEC")
        print("Use --help for available options")

if __name__ == '__main__':
    main()
