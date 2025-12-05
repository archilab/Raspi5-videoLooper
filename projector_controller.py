#!/usr/bin/env python3
"""
Serial Communication Module for Projector Control
Handles USB-to-serial communication with projectors/beamers
"""

import serial
import logging
import time
import threading
from pathlib import Path
import json
import re
import subprocess

class ProjectorController:
    def __init__(self, log_file="/var/log/video_looper.log"):
        self.logger = logging.getLogger(__name__)
        self.serial_connection = None
        self.is_connected = False
        self.config = {}
        
    def load_config_from_file(self, config_file_path):
        """Load projector configuration from a text file in video folder"""
        try:
            config_path = Path(config_file_path)
            if not config_path.exists():
                self.logger.warning(f"Config file not found: {config_file_path}")
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
            
            self.logger.info(f"Loaded projector config: {self.config}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading config file {config_file_path}: {e}")
            return False
    
    def get_default_config(self):
        """Get default projector configuration (Optoma defaults)"""
        return {
            'serial_port': '/dev/ttyUSB0',
            'baud_rate': 9600,
            'timeout': 5,
            'start_command': '~0000 1',
            'stop_command': '~0000 0',
            'start_delay': 0,
            'stop_delay': 0,
            'enable_projector': False,
            'configure_stty': True  # Apply stty configuration for Optoma projectors
        }
    
    def configure_serial_port(self, port):
        """Configure serial port using stty (for Optoma projectors)"""
        if not self.config.get('configure_stty', True):
            return True
        
        try:
            baud_rate = int(self.config.get('baud_rate', 9600))
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
            
            if result.returncode == 0:
                self.logger.debug(f"Serial port {port} configured with stty")
                return True
            else:
                self.logger.warning(f"stty configuration failed: {result.stderr.decode()}")
                return False
                
        except Exception as e:
            self.logger.warning(f"Error configuring serial port with stty: {e}")
            return False
    
    def connect(self):
        """Connect to projector via serial"""
        if not self.config.get('enable_projector', False):
            self.logger.info("Projector control disabled in config")
            return True
        
        try:
            port = self.config.get('serial_port', '/dev/ttyUSB0')
            baud_rate = int(self.config.get('baud_rate', 9600))
            timeout = int(self.config.get('timeout', 5))
            
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
            self.logger.info(f"Connected to projector on {port} at {baud_rate} baud")
            return True
            
        except serial.SerialException as e:
            self.logger.error(f"Failed to connect to projector: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error connecting to projector: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from projector"""
        if self.serial_connection and self.is_connected:
            try:
                self.serial_connection.close()
                self.is_connected = False
                self.logger.info("Disconnected from projector")
            except Exception as e:
                self.logger.error(f"Error disconnecting from projector: {e}")
    
    def send_command(self, command):
        """Send a command to the projector"""
        if not self.is_connected or not self.serial_connection:
            self.logger.warning("Not connected to projector, cannot send command")
            return False
        
        try:
            # For Optoma: commands end with \r (carriage return), not \r\n
            # Add carriage return if not present
            if not command.endswith('\r'):
                command = command + '\r'
            
            self.serial_connection.write(command.encode())
            self.logger.info(f"Sent command to projector: {repr(command)}")
            
            # Wait for response if configured
            if self.config.get('wait_for_response', False):
                time.sleep(0.5)  # Give projector time to respond
                response = self.serial_connection.read_all().decode().strip()
                if response:
                    self.logger.info(f"Projector response: {response}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending command to projector: {e}")
            return False
    
    def start_projector(self):
        """Start the projector"""
        if not self.config.get('enable_projector', False):
            self.logger.info("Projector control disabled, skipping start")
            return True
        
        start_delay = int(self.config.get('start_delay', 0))
        if start_delay > 0:
            self.logger.info(f"Waiting {start_delay} seconds before starting projector...")
            time.sleep(start_delay)
        
        start_command = self.config.get('start_command', '~0000 1')
        return self.send_command(start_command)
    
    def stop_projector(self):
        """Stop the projector"""
        if not self.config.get('enable_projector', False):
            self.logger.info("Projector control disabled, skipping stop")
            return True
        
        stop_delay = int(self.config.get('stop_delay', 0))
        if stop_delay > 0:
            self.logger.info(f"Waiting {stop_delay} seconds before stopping projector...")
            time.sleep(stop_delay)
        
        stop_command = self.config.get('stop_command', '~0000 0')
        return self.send_command(stop_command)
    
    def test_connection(self):
        """Test projector connection"""
        if not self.config.get('enable_projector', False):
            return True
        
        if self.connect():
            # Try to send a status command if available
            status_command = self.config.get('status_command', '')
            if status_command:
                self.send_command(status_command)
            self.disconnect()
            return True
        return False
    
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

def main():
    """Test the projector controller"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Projector Controller')
    parser.add_argument('--config', help='Path to config file')
    parser.add_argument('--test', action='store_true', help='Test connection')
    parser.add_argument('--list-ports', action='store_true', help='List available serial ports')
    parser.add_argument('--start', action='store_true', help='Start projector')
    parser.add_argument('--stop', action='store_true', help='Stop projector')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    controller = ProjectorController()
    
    if args.list_ports:
        print("Available serial ports:")
        ports = controller.get_available_ports()
        for port in ports:
            print(f"  {port['device']}: {port['description']} ({port['manufacturer']})")
        return
    
    if args.config:
        if controller.load_config_from_file(args.config):
            print("✓ Config loaded successfully")
        else:
            print("✗ Failed to load config")
            return
    
    if args.test:
        print("Testing projector connection...")
        if controller.test_connection():
            print("✓ Projector connection test successful")
        else:
            print("✗ Projector connection test failed")
    
    elif args.start:
        if controller.load_config_from_file(args.config):
            if controller.connect():
                controller.start_projector()
                controller.disconnect()
    
    elif args.stop:
        if controller.load_config_from_file(args.config):
            if controller.connect():
                controller.stop_projector()
                controller.disconnect()
    
    else:
        print("Projector Controller")
        print("Use --help for available options")

if __name__ == '__main__':
    main()
