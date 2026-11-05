#!/usr/bin/env python3
"""
Serial Communication Module for Projector Control
Handles USB-to-serial communication with projectors/beamers
"""

import glob
import serial
import logging
import time
from pathlib import Path
import json
import subprocess
from constants import (
    DEFAULT_SERIAL_PORT, DEFAULT_BAUD_RATE, DEFAULT_SERIAL_TIMEOUT,
    DEFAULT_START_COMMAND, DEFAULT_STOP_COMMAND,
    BRAND_START_COMMANDS, BRAND_STOP_COMMANDS, BRAND_START_DELAY, BRAND_STOP_DELAY,
    BRAND_VIDEO_START_DELAY, PROJECTOR_COMMAND_GAP, USB_SERIAL_PORTS
)

class ProjectorController:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.serial_connection = None
        self.is_connected = False
        self.config = {}
        
    def load_config_from_file(self, config_file_path):
        """Load projector configuration from a text file in video folder"""
        try:
            config_path = Path(config_file_path)
            if not config_path.exists():
                return False
            
            with open(config_path, 'r') as f:
                content = f.read().strip()
            
            # Parse configuration - support both JSON and simple key=value format
            if content.startswith('{'):
                # JSON format
                self.config = json.loads(content)
            else:
                # Simple key=value format
                self.config = {}
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Convert boolean and numeric values
                            if value.lower() == 'true':
                                self.config[key] = True
                            elif value.lower() == 'false':
                                self.config[key] = False
                            elif value.isdigit():
                                self.config[key] = int(value)
                            elif value.replace('.', '', 1).isdigit():
                                self.config[key] = float(value)
                            else:
                                self.config[key] = value
            
            return True
            
        except (OSError, ValueError) as e:
            self.logger.error(f"Error loading config: {e}")
            return False
    
    def find_usb_serial_port(self):
        """Find the first USB serial adapter, or None if none is connected"""
        for pattern in USB_SERIAL_PORTS:
            ports = sorted(glob.glob(pattern))
            if ports:
                return ports[0]
        return None

    def get_default_config(self):
        """Settings for a folder with no settings file: every known brand, if there's an adapter"""
        port = self.find_usb_serial_port()
        if not port:
            return {'enable_projector': False}
        return {
            'enable_projector': True,
            'serial_port': port,
            'baud_rate': DEFAULT_BAUD_RATE,
            'timeout': DEFAULT_SERIAL_TIMEOUT,
            'start_commands': BRAND_START_COMMANDS,
            'stop_commands': BRAND_STOP_COMMANDS,
            'start_delay': BRAND_START_DELAY,
            'stop_delay': BRAND_STOP_DELAY,
            'video_start_delay': BRAND_VIDEO_START_DELAY,
            'configure_stty': True
        }

    def configure_serial_port(self, port):
        """Configure serial port using stty (for Optoma projectors)"""
        if not self.config.get('configure_stty', True):
            return True
        
        try:
            baud_rate = int(self.config.get('baud_rate', DEFAULT_BAUD_RATE))
            # Apply stty configuration: 9600 cs8 -cstopb -parenb -ixon -ixoff -crtscts
            stty_cmd = [
                'stty', '-F', port,
                str(baud_rate),
                'cs8',
                '-cstopb',
                '-parenb',
                '-ixon',
                '-ixoff',
                '-crtscts'
            ]
            
            result = subprocess.run(
                stty_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            
            return result.returncode == 0
                
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
    
    def connect(self):
        """Connect to projector via serial, if projector control is enabled"""
        if not self.config.get('enable_projector', False):
            return True
        return self._open_port()

    def _open_port(self):
        """Open the configured serial port"""
        try:
            port = self.config.get('serial_port', DEFAULT_SERIAL_PORT)
            baud_rate = int(self.config.get('baud_rate', DEFAULT_BAUD_RATE))
            timeout = int(self.config.get('timeout', DEFAULT_SERIAL_TIMEOUT))

            # Configure serial port with stty if enabled
            self.configure_serial_port(port)

            self.serial_connection = serial.Serial(
                port=port,
                baudrate=baud_rate,
                timeout=timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,  # -ixon -ixoff
                rtscts=False    # -crtscts
            )

            self.is_connected = True
            return True

        except (OSError, ValueError, TypeError) as e:
            self.logger.error(f"Failed to connect: {e}")
            self.is_connected = False
            return False

    def test_connection(self):
        """
        Check that the serial port opens, even if projector control is disabled.
        Sends nothing, so the projector isn't affected. This shows the adapter and
        settings work, but not that a projector is listening.
        """
        if not self._open_port():
            return False
        self.disconnect()
        return True

    def disconnect(self):
        """Disconnect from projector"""
        if self.serial_connection and self.is_connected:
            try:
                self.serial_connection.close()
                self.is_connected = False
            except OSError:
                pass
    
    def send_command(self, command):
        """Send a command to the projector"""
        if not self.is_connected or not self.serial_connection:
            return False
        
        try:
            if not command.endswith('\r'):
                command = command + '\r'
            
            self.serial_connection.write(command.encode())
            
            if self.config.get('wait_for_response', False):
                time.sleep(0.5)
                self.serial_connection.read_all()
            
            return True
            
        except OSError as e:
            self.logger.error(f"Error sending command: {e}")
            return False
    
    def _send_commands(self, commands):
        """Send commands in order, returning True if at least one was sent"""
        sent = False
        for index, command in enumerate(commands):
            if index:
                time.sleep(PROJECTOR_COMMAND_GAP)
            sent = self.send_command(command) or sent
        return sent

    def start_projector(self):
        """Start the projector"""
        if not self.config.get('enable_projector', False):
            return True

        start_delay = int(self.config.get('start_delay', 0))
        if start_delay > 0:
            time.sleep(start_delay)

        return self._send_commands(self.config.get('start_commands') or
                                   [self.config.get('start_command', DEFAULT_START_COMMAND)])

    def stop_projector(self):
        """Stop the projector"""
        if not self.config.get('enable_projector', False):
            return True

        stop_delay = int(self.config.get('stop_delay', 0))
        if stop_delay > 0:
            time.sleep(stop_delay)

        return self._send_commands(self.config.get('stop_commands') or
                                   [self.config.get('stop_command', DEFAULT_STOP_COMMAND)])

    def get_available_ports(self):
        """Get list of available serial ports"""
        import serial.tools.list_ports
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append({
                'device': port.device,
                'description': port.description,
                'manufacturer': port.manufacturer
            })
        return ports
