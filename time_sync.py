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
    
    def sync_time(self):
        """Main time synchronization method"""
        if self.check_internet_connection():
            if self.sync_with_ntp() or self.sync_with_ntpdate():
                self.last_sync = datetime.now()
                return True
        
        if self.setup_rtc():
            self.last_sync = datetime.now()
            return True
        
        return True
    
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

