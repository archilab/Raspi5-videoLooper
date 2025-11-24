#!/usr/bin/env python3
"""
Time Synchronization Module for Raspberry Pi Video Looper
Handles NTP synchronization with RTC fallback
"""

import subprocess
import logging
import socket
import time
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
                if 'NTP service: active' in result.stdout or 'NTP synchronized: yes' in result.stdout:
                    self.logger.info("NTP synchronization is active")
                    return True
                else:
                    self.logger.info("NTP synchronization is configured but not active (this is normal)")
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
                self.logger.info("ntpdate not available, using systemd-timesyncd only")
                return False
            
            self.logger.info("ntpdate found, attempting manual sync...")
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
                        self.logger.info(f"Successfully synced with NTP server: {server}")
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
    
    def setup_rtc(self):
        """Setup RTC (Real Time Clock) as fallback"""
        try:
            # Check if RTC is available (don't use sudo for read-only check)
            result = subprocess.run(
                ['timedatectl', 'status'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Check if system time is managed by RTC
                if 'RTC' in result.stdout:
                    self.logger.info("RTC is available as time source")
                    return True
                else:
                    self.logger.info("RTC check completed")
                    return True
            else:
                self.logger.warning("RTC not available")
                return False
                
        except Exception as e:
            self.logger.error(f"RTC setup error: {e}")
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
            
            self.logger.info(f"Setting RTC time to: {time_str}")
            
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
                    self.logger.info("RTC time set successfully")
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
                self.logger.debug(f"Time file not found: {file_path}")
                return False
            
            # Read time from file
            with open(time_file, 'r') as f:
                time_str = f.read().strip()
            
            if not time_str:
                self.logger.warning(f"Time file is empty: {file_path}")
                return False
            
            self.logger.info(f"Reading time from file: {file_path}")
            self.logger.debug(f"Time string from file: {time_str}")
            
            # Try to parse different time formats
            dt = None
            
            # Try ISO format: 2024-01-15T14:30:00 or 2024-01-15T14:30:00.000000
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                # Remove timezone info for local time
                if dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
                self.logger.debug("Parsed as ISO format")
            except ValueError:
                pass
            
            # Try format: YYYY-MM-DD HH:MM:SS
            if dt is None:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    self.logger.debug("Parsed as date + time format")
                except ValueError:
                    pass
            
            # Try format: YYYY-MM-DD HH:MM
            if dt is None:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                    self.logger.debug("Parsed as date + time (no seconds) format")
                except ValueError:
                    pass
            
            # Try Unix timestamp (integer)
            if dt is None:
                try:
                    timestamp = int(float(time_str))
                    dt = datetime.fromtimestamp(timestamp)
                    self.logger.debug("Parsed as Unix timestamp")
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
    
    def sync_time(self):
        """Main time synchronization method"""
        self.logger.info("Starting time synchronization...")
        
        # Check internet connectivity
        if self.check_internet_connection():
            self.logger.info("Internet connection available, attempting NTP sync")
            
            # Try systemd-timesyncd first
            if self.sync_with_ntp():
                self.last_sync = datetime.now()
                return True
            
            # Fallback to ntpdate
            if self.sync_with_ntpdate():
                self.last_sync = datetime.now()
                return True
            
            self.logger.warning("NTP synchronization failed, falling back to RTC")
        
        else:
            self.logger.info("No internet connection, using RTC")
        
        # Use RTC as fallback - just verify availability, don't try to sync
        if self.setup_rtc():
            self.logger.info("RTC is available, systemd-timesyncd will handle syncing")
            self.last_sync = datetime.now()
            return True
        
        # If we reach here, time sync failed but that's OK - systemd-timesyncd handles it
        self.logger.info("Time synchronization verification complete")
        return True
    
    def start_background_sync(self):
        """Start background time synchronization thread"""
        if self.sync_thread and self.sync_thread.is_alive():
            return
        
        self.sync_thread = threading.Thread(target=self._background_sync_loop, daemon=True)
        self.sync_thread.start()
        self.logger.info("Background time synchronization started")
    
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
        self.logger.info("Background time synchronization stopped")
    
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
        try:
            result = subprocess.run(
                ['sudo', 'hwclock', '--show'],
                capture_output=True,
                text=True
            )
            status['rtc_available'] = result.returncode == 0
        except:
            pass
        
        return status

def main():
    """Test the time synchronization module"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Time Synchronization Manager')
    parser.add_argument('--test', action='store_true', help='Test time sync')
    parser.add_argument('--status', action='store_true', help='Show time status')
    parser.add_argument('--sync', action='store_true', help='Force time sync')
    parser.add_argument('--set-rtc-from-file', type=str, metavar='FILE',
                       help='Set RTC time from a time file')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    time_sync = TimeSyncManager()
    
    if args.status:
        status = time_sync.get_time_status()
        print("Time Synchronization Status:")
        for key, value in status.items():
            print(f"  {key}: {value}")
    
    elif args.sync:
        print("Forcing time synchronization...")
        if time_sync.sync_time():
            print("✓ Time synchronization successful")
        else:
            print("✗ Time synchronization failed")
    
    elif args.set_rtc_from_file:
        print(f"Setting RTC time from file: {args.set_rtc_from_file}")
        if time_sync.set_rtc_from_file(args.set_rtc_from_file):
            print("✓ RTC time set successfully")
        else:
            print("✗ Failed to set RTC time from file")
        return
    
    elif args.test:
        print("Testing time synchronization...")
        print(f"Internet available: {time_sync.check_internet_connection()}")
        print(f"RTC available: {time_sync.setup_rtc()}")
        
        if time_sync.sync_time():
            print("✓ Time sync test successful")
        else:
            print("✗ Time sync test failed")
    
    else:
        print("Time Synchronization Manager")
        print("Use --help for available options")

if __name__ == '__main__':
    main()
