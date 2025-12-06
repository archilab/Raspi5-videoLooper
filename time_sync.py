#!/usr/bin/env python3
"""
Time Synchronization Module for Raspberry Pi Video Looper
Default time base is RTC. Automatically falls back to NTP if RTC is not available.
Supports syncing RTC with NTP or setting time manually.
"""

import subprocess
import logging
import socket
import time
import os
from datetime import datetime
import threading
import requests

class TimeSyncManager:
    def __init__(self, log_file="/var/log/video_looper.log"):
        self.logger = logging.getLogger(__name__)
        self.sync_interval = 3600  # Sync every hour
        self.last_sync = None
        self.sync_thread = None
        self.running = True
    
    def display_message_on_screen(self, message):
        """
        Display a message on the HDMI screen (TTY1)
        Args:
            message: Message string to display
        """
        try:
            tty1_path = '/dev/tty1'
            if os.path.exists(tty1_path):
                with open(tty1_path, 'w') as tty1:
                    # Clear screen and display message
                    tty1.write('\033[2J\033[H')  # Clear screen and move cursor to home
                    tty1.write(f"\n\n{message}\n\n")
                    tty1.flush()
        except (PermissionError, OSError):
            pass
        except Exception:
            pass
        
    def check_internet_connection(self, timeout=5):
        """Check if internet connection is available"""
        try:
            # Try to connect to a reliable NTP server
            socket.create_connection(("8.8.8.8", 53), timeout)
            return True
        except OSError:
            try:
                # Alternative check using requests
                requests.get("http://www.google.com", timeout=timeout)
                return True
            except:
                return False
    
    def sync_with_ntp(self):
        """Synchronize system time with NTP servers"""
        try:
            # Check if we have permission to set NTP (requires admin)
            # Just check status instead of trying to enable (which requires sudo)
            result = subprocess.run(
                ['timedatectl', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Check if NTP is already enabled
                return True
            else:
                self.logger.warning(f"Could not check NTP status: {result.stderr}")
                return False
                
        except FileNotFoundError:
            self.logger.warning("timedatectl not available")
            return False
        except subprocess.TimeoutExpired:
            self.logger.error("NTP status check timed out")
            return False
        except Exception as e:
            self.logger.error(f"NTP synchronization error: {e}")
            return False
    
    def sync_with_ntpdate(self):
        """Alternative NTP sync using ntpdate (if available)"""
        try:
            # Check if ntpdate is available
            import shutil
            if not shutil.which('ntpdate'):
                return False
            ntp_servers = [
                'pool.ntp.org',
                'time.google.com',
                'time.cloudflare.com',
                'time.nist.gov'
            ]
            
            for server in ntp_servers:
                try:
                    result = subprocess.run(
                        ['sudo', 'ntpdate', '-s', server],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if result.returncode == 0:
                        return True
                        
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"NTP server {server} timed out")
                    continue
                except Exception as e:
                    self.logger.warning(f"Error syncing with {server}: {e}")
                    continue
            
            return False
            
        except Exception as e:
            self.logger.error(f"NTP sync error: {e}")
            return False
    
    def check_rtc_available(self):
        """
        Check if RTC (Real Time Clock) is available
        Returns:
            bool: True if RTC is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['sudo', 'hwclock', '--show'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def load_time_from_rtc(self):
        """
        Load system time from RTC (Real Time Clock)
        This is the default time source
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = subprocess.run(
                ['sudo', 'hwclock', '--hctosys'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Failed to load time from RTC: {e}")
            return False
    
    def set_rtc_from_datetime(self, dt):
        """
        Set RTC time from a datetime object
        Args:
            dt: datetime object with the time to set
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Format datetime for timedatectl: YYYY-MM-DD HH:MM:SS
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Set system time using timedatectl (requires sudo)
            result = subprocess.run(
                ['sudo', 'timedatectl', 'set-time', time_str],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Sync system time to RTC
                rtc_result = subprocess.run(
                    ['sudo', 'hwclock', '--systohc'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if rtc_result.returncode == 0:
                    return True
                else:
                    self.logger.warning(f"Failed to sync RTC: {rtc_result.stderr}")
                    return False
            else:
                self.logger.error(f"Failed to set system time: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout while setting RTC time")
            return False
        except Exception as e:
            self.logger.error(f"Error setting RTC time: {e}")
            return False
    
    def set_rtc_from_file(self, file_path):
        """
        Set RTC time from a file on USB drive
        Supports multiple time formats:
        - ISO format: 2024-01-15T14:30:00
        - Date + Time: 2024-01-15 14:30:00
        - Timestamp: 1705324200 (Unix timestamp)
        Args:
            file_path: Path to the time file
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            from pathlib import Path
            
            time_file = Path(file_path)
            
            if not time_file.exists():
                return False
            
            with open(time_file, 'r') as f:
                time_str = f.read().strip()
            
            if not time_str:
                return False
            
            # Try to parse different time formats
            dt = None
            
            # Try ISO format: 2024-01-15T14:30:00 or 2024-01-15T14:30:00.000000
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                if dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
            except ValueError:
                pass
            
            if dt is None:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass
            
            if dt is None:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    pass
            
            if dt is None:
                try:
                    timestamp = int(float(time_str))
                    dt = datetime.fromtimestamp(timestamp)
                except (ValueError, OSError):
                    pass
            
            if dt is None:
                self.logger.error(f"Could not parse time from file. Format: '{time_str}'")
                self.logger.error("Supported formats: ISO (2024-01-15T14:30:00), Date+Time (2024-01-15 14:30:00), Unix timestamp")
                return False
            
            # Set RTC time
            return self.set_rtc_from_datetime(dt)
            
        except PermissionError:
            self.logger.error(f"Permission denied reading time file: {file_path}")
            return False
        except Exception as e:
            self.logger.error(f"Error reading time file: {e}")
            return False
    
    def sync_rtc_with_ntp(self):
        """
        Sync RTC with NTP if available
        First syncs system time with NTP, then writes it to RTC
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.check_internet_connection():
            self.logger.warning("Internet connection not available for NTP sync")
            return False
        
        # Try to sync system time with NTP first
        ntp_synced = False
        
        # Try systemd-timesyncd first
        try:
            result = subprocess.run(
                ['sudo', 'timedatectl', 'set-ntp', 'true'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Wait a bit for NTP to sync
                time.sleep(3)
                # Check if NTP sync succeeded
                status_result = subprocess.run(
                    ['timedatectl', 'status'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if 'NTP synchronized: yes' in status_result.stdout:
                    ntp_synced = True
        except Exception:
            pass
        
        # Try ntpdate as alternative
        if not ntp_synced:
            ntp_synced = self.sync_with_ntpdate()
        
        if ntp_synced:
            # Sync system time to RTC
            try:
                rtc_result = subprocess.run(
                    ['sudo', 'hwclock', '--systohc'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if rtc_result.returncode == 0:
                    self.last_sync = datetime.now()
                    return True
            except Exception as e:
                self.logger.error(f"Failed to sync RTC after NTP sync: {e}")
        
        return False
    
    def set_time_manually(self, time_str):
        """
        Set system time and RTC manually
        Supports multiple time formats:
        - ISO format: 2024-01-15T14:30:00
        - Date + Time: 2024-01-15 14:30:00
        - Date + Time (short): 2024-01-15 14:30
        Args:
            time_str: Time string in supported format
        Returns:
            bool: True if successful, False otherwise
        """
        # Parse time string
        dt = None
        
        # Try ISO format
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except ValueError:
            pass
        
        if dt is None:
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
        
        if dt is None:
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
            except ValueError:
                pass
        
        if dt is None:
            self.logger.error(f"Could not parse time format: '{time_str}'")
            return False
        
        # Set time using the existing method
        return self.set_rtc_from_datetime(dt)
    
    def sync_with_ntp_fallback(self):
        """
        Sync system time with NTP as fallback (without writing to RTC)
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.check_internet_connection():
            return False
        
        # Try systemd-timesyncd first
        try:
            result = subprocess.run(
                ['sudo', 'timedatectl', 'set-ntp', 'true'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Wait a bit for NTP to sync
                time.sleep(3)
                # Check if NTP sync succeeded
                status_result = subprocess.run(
                    ['timedatectl', 'status'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if 'NTP synchronized: yes' in status_result.stdout:
                    return True
        except Exception:
            pass
        
        # Try ntpdate as alternative
        if self.sync_with_ntpdate():
            return True
        
        return False
    
    def sync_time(self):
        """
        Main time synchronization method - loads time from RTC by default
        Falls back to NTP automatically if RTC is not available
        Returns:
            bool: True if successful, False otherwise
        """
        # Primary: Load time from RTC
        if self.check_rtc_available():
            if self.load_time_from_rtc():
                self.last_sync = datetime.now()
                return True
            else:
                self.logger.warning("Failed to load time from RTC, trying NTP fallback")
                # Fall through to NTP fallback
        else:
            self.logger.warning("RTC not available, trying NTP fallback")
        
        # Fallback: Try NTP if RTC is not available or failed
        if self.sync_with_ntp_fallback():
            self.last_sync = datetime.now()
            self.logger.info("Time synchronized with NTP (RTC fallback)")
            return True
        
        # Neither RTC nor NTP available
        self.logger.warning("Neither RTC nor NTP available for time synchronization")
        warning_msg = "WARNING: RTC and NTP are not available\nSystem time may be inaccurate"
        self.display_message_on_screen(warning_msg)
        # Keep warning visible for 10 seconds
        time.sleep(10)
        return False
    
    def start_background_sync(self):
        """Start background time synchronization thread"""
        if self.sync_thread and self.sync_thread.is_alive():
            return
        
        self.sync_thread = threading.Thread(target=self._background_sync_loop, daemon=True)
        self.sync_thread.start()
    
    def _background_sync_loop(self):
        """Background synchronization loop"""
        while self.running:
            try:
                self.sync_time()
                time.sleep(self.sync_interval)
            except Exception as e:
                self.logger.error(f"Background sync error: {e}")
                time.sleep(60)  # Wait 1 minute on error
    
    def stop_background_sync(self):
        """Stop background synchronization"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
    
    def get_time_status(self):
        """Get current time synchronization status"""
        status = {
            'current_time': datetime.now().isoformat(),
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'internet_available': self.check_internet_connection(),
            'ntp_enabled': False,
            'rtc_available': False
        }
        
        # Check NTP status
        try:
            result = subprocess.run(
                ['timedatectl', 'status'],
                capture_output=True,
                text=True
            )
            if 'NTP service: active' in result.stdout:
                status['ntp_enabled'] = True
        except:
            pass
        
        # Check RTC availability
        status['rtc_available'] = self.check_rtc_available()
        
        return status


def main():
    """CLI interface for time synchronization"""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description='Time Synchronization Manager for Video Looper')
    parser.add_argument('--sync-rtc-ntp', action='store_true',
                        help='Sync RTC with NTP if available')
    parser.add_argument('--set-time', type=str, metavar='TIME',
                        help='Set time manually (format: YYYY-MM-DD HH:MM:SS or YYYY-MM-DD HH:MM)')
    parser.add_argument('--set-from-file', type=str, metavar='FILE',
                        help='Set RTC time from file on USB drive')
    parser.add_argument('--status', action='store_true',
                        help='Show current time synchronization status')
    parser.add_argument('--log-file', type=str, default='/var/log/video_looper.log',
                        help='Path to log file')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    manager = TimeSyncManager(args.log_file)
    
    if args.sync_rtc_ntp:
        print("Syncing RTC with NTP...")
        if manager.sync_rtc_with_ntp():
            print("Successfully synced RTC with NTP")
            sys.exit(0)
        else:
            print("Failed to sync RTC with NTP")
            sys.exit(1)
    
    elif args.set_time:
        print(f"Setting time to: {args.set_time}")
        if manager.set_time_manually(args.set_time):
            print("Successfully set time")
            sys.exit(0)
        else:
            print("Failed to set time")
            sys.exit(1)
    
    elif args.set_from_file:
        print(f"Setting RTC time from file: {args.set_from_file}")
        if manager.set_rtc_from_file(args.set_from_file):
            print("Successfully set RTC time from file")
            sys.exit(0)
        else:
            print("Failed to set RTC time from file")
            sys.exit(1)
    
    elif args.status:
        status = manager.get_time_status()
        print("Time Synchronization Status:")
        print(f"  Current Time: {status['current_time']}")
        print(f"  Last Sync: {status['last_sync'] or 'Never'}")
        print(f"  Internet Available: {status['internet_available']}")
        print(f"  NTP Enabled: {status['ntp_enabled']}")
        print(f"  RTC Available: {status['rtc_available']}")
        sys.exit(0)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

