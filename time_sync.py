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
            # Use systemd-timesyncd if available
            result = subprocess.run(
                ['sudo', 'timedatectl', 'set-ntp', 'true'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self.logger.info("NTP synchronization enabled successfully")
                return True
            else:
                self.logger.warning(f"NTP sync failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("NTP synchronization timed out")
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
            # Check if RTC is available
            result = subprocess.run(
                ['sudo', 'hwclock', '--show'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info("RTC is available as time source")
                return True
            else:
                self.logger.warning("RTC not available")
                return False
                
        except Exception as e:
            self.logger.error(f"RTC setup error: {e}")
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
        
        # Use RTC as fallback
        if self.setup_rtc():
            try:
                # Sync system time with RTC
                subprocess.run(
                    ['sudo', 'hwclock', '--hctosys'],
                    check=True,
                    timeout=10
                )
                self.logger.info("System time synced with RTC")
                self.last_sync = datetime.now()
                return True
            except Exception as e:
                self.logger.error(f"RTC sync failed: {e}")
                return False
        
        self.logger.error("All time synchronization methods failed")
        return False
    
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
