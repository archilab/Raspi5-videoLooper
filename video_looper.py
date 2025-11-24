#!/usr/bin/env python3
"""
Raspberry Pi 5 Video Looper with VLC
Supports day/time control through folder naming convention
"""

import os
import sys
import time
import subprocess
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
import signal
import json
from time_sync import TimeSyncManager
from projector_controller import ProjectorController
from hdmi_controller import HDMIController
from usb_sync import USBSync

class VideoLooper:
    def __init__(self, videos_path=None, log_file=None):
        # Use fixed paths for looper user
        if videos_path is None:
            videos_path = "/home/looper/videos"
        if log_file is None:
            log_file = "/var/log/video_looper.log"
            
        self.videos_path = Path(videos_path)
        self.log_file = log_file
        self.current_process = None
        self.current_folder = None
        self.running = True
        
        # Setup logging
        self.setup_logging()
        
        # Initialize time synchronization
        self.time_sync = TimeSyncManager(log_file)
        
        # Initialize projector controller
        self.projector = ProjectorController(log_file)
        
        # Initialize HDMI controller
        self.hdmi = HDMIController(log_file)
        
        # Initialize USB sync
        self.usb_sync = USBSync(str(self.videos_path), log_file)
        
        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.logger.info("Video Looper initialized")
    
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self.stop_video(standby_hdmi=True)
        self.time_sync.stop_background_sync()
        self.projector.disconnect()
        sys.exit(0)
    
    def parse_folder_name(self, folder_name):
        """
        Parse folder name to extract scheduling information
        Expected format: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM
        Example: 2024-01-01_to_2024-01-31_0900_to_1800
        """
        pattern = r'(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_(\d{4})_to_(\d{4})'
        match = re.match(pattern, folder_name)
        
        if not match:
            return None
        
        try:
            start_date = datetime.strptime(match.group(1), '%Y-%m-%d').date()
            end_date = datetime.strptime(match.group(2), '%Y-%m-%d').date()
            start_time = datetime.strptime(match.group(3), '%H%M').time()
            end_time = datetime.strptime(match.group(4), '%H%M').time()
            
            return {
                'start_date': start_date,
                'end_date': end_date,
                'start_time': start_time,
                'end_time': end_time
            }
        except ValueError:
            return None
    
    def is_folder_active(self, folder_name):
        """Check if a folder should be active based on current date and time"""
        schedule = self.parse_folder_name(folder_name)
        if not schedule:
            return False
        
        now = datetime.now()
        current_date = now.date()
        current_time = now.time()
        
        # Check if current date is within the date range
        if not (schedule['start_date'] <= current_date <= schedule['end_date']):
            return False
        
        # Check if current time is within the daily time range
        # Create datetime objects for proper time comparison
        start_datetime = datetime.combine(now.date(), schedule['start_time'])
        end_datetime = datetime.combine(now.date(), schedule['end_time'])
        current_datetime = datetime.combine(now.date(), current_time)
        
        if not (start_datetime <= current_datetime <= end_datetime):
            return False
        
        return True
    
    def get_video_files(self, folder_path):
        """Get all video files from a folder"""
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
        video_files = []
        
        for file_path in folder_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in video_extensions:
                video_files.append(file_path)
        
        return sorted(video_files)
    
    def has_projector_config(self, folder_path):
        """Check if folder has projector configuration file"""
        config_files = ['projector.txt', 'projector.conf', 'config.txt']
        
        for config_file in config_files:
            config_path = folder_path / config_file
            if config_path.exists():
                return True
        
        return False
    
    def load_projector_config(self, folder_path):
        """Load projector configuration from folder"""
        config_files = ['projector.txt', 'projector.conf', 'config.txt']
        
        for config_file in config_files:
            config_path = folder_path / config_file
            if config_path.exists():
                self.logger.info(f"Loading projector config from: {config_path}")
                return self.projector.load_config_from_file(str(config_path))
        
        # Use default config if no config file found
        self.projector.config = self.projector.get_default_config()
        return True
    
    def handle_video_start_delay(self, folder_path):
        """Handle video start delay if configured"""
        start_delay = self.projector.config.get('video_start_delay', 0)
        # Convert to int in case it's a string from config file
        try:
            start_delay = int(start_delay)
            if start_delay > 0:
                self.logger.info(f"Video start delay configured: {start_delay} seconds")
                time.sleep(start_delay)
                return True
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid video_start_delay value: {start_delay}")
        return False
    
    def find_active_folder(self):
        """Find the folder that should be active based on current date/time"""
        if not self.videos_path.exists():
            self.logger.error(f"Videos path {self.videos_path} does not exist")
            return None
        
        active_folders = []
        
        for folder_path in self.videos_path.iterdir():
            if folder_path.is_dir():
                if self.is_folder_active(folder_path.name):
                    video_files = self.get_video_files(folder_path)
                    if video_files:
                        active_folders.append((folder_path, video_files))
        
        if not active_folders:
            self.logger.info("No active folders found")
            return None
        
        # If multiple folders are active, use the one with the most recent start date
        active_folders.sort(key=lambda x: self.parse_folder_name(x[0].name)['start_date'], reverse=True)
        
        return active_folders[0]
    
    def start_video(self, video_files, folder_path):
        """Start VLC with video files in loop mode and control projector"""
        if not video_files:
            self.logger.error("No video files provided")
            return False
        
        # Wake HDMI display before starting video playback
        if self.hdmi.is_available():
            self.logger.info("Waking HDMI display...")
            if not self.hdmi.wake_hdmi():
                self.logger.warning("Failed to wake HDMI display, continuing anyway")
            else:
                # Give display time to wake up
                time.sleep(2)
        
        # Only load and use projector config if projector.txt exists in folder
        if self.has_projector_config(folder_path):
            self.logger.info("Projector config file found in folder")
            # Load projector configuration for this folder
            self.load_projector_config(folder_path)
            
            # Connect to projector if enabled
            if self.projector.config.get('enable_projector', False):
                if not self.projector.connect():
                    self.logger.warning("Failed to connect to projector, continuing without projector control")
            
            # Start projector if enabled
            if self.projector.config.get('enable_projector', False):
                self.logger.info("Starting projector...")
                if not self.projector.start_projector():
                    self.logger.warning("Failed to start projector")
            
            # Handle video start delay
            self.handle_video_start_delay(folder_path)
        else:
            self.logger.info("No projector config file found, skipping projector control")
        
        # Create VLC command using cvlc (command-line VLC)
        vlc_cmd = [
            'cvlc',
            '--intf', 'dummy',  # No GUI
            '--fullscreen',  # Fullscreen mode
            '--loop',  # Loop the playlist
            '--no-osd',  # No on-screen display
            '--no-audio',  # no audio
            '--quiet',  # Reduce output
        ]
        
        # Add all video files to the command
        vlc_cmd.extend([str(f) for f in video_files])
        
        try:
            self.logger.info(f"Starting VLC with {len(video_files)} video files")
            self.logger.info(f"VLC command: {' '.join(vlc_cmd)}")
            
            # Create log file for VLC output in user-writable location
            import os
            user_home = os.path.expanduser('~')
            vlc_log_file = os.path.join(user_home, 'video_looper_vlc.log')
            
            self.current_process = subprocess.Popen(
                vlc_cmd,
                stdout=open(vlc_log_file, 'a'),
                stderr=subprocess.STDOUT
            )
            self.logger.info(f"VLC process started with PID: {self.current_process.pid}")
            # Store current folder for stop operations
            self.current_folder = folder_path
            return True
        except Exception as e:
            self.logger.error(f"Failed to start VLC: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def stop_video(self, standby_hdmi=False):
        """
        Stop the current video playback and projector
        Args:
            standby_hdmi: If True, put HDMI display in standby after stopping video
        """
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
                self.logger.info("Video playback stopped")
            except subprocess.TimeoutExpired:
                self.logger.warning("Force killing VLC process")
                self.current_process.kill()
                self.current_process.wait()
            except Exception as e:
                self.logger.error(f"Error stopping video: {e}")
            finally:
                self.current_process = None
        
        # Stop projector only if there's a config file for the current folder
        if self.current_folder and self.has_projector_config(self.current_folder):
            if self.projector.config.get('enable_projector', False):
                self.logger.info("Stopping projector...")
                if not self.projector.stop_projector():
                    self.logger.warning("Failed to stop projector")
                self.projector.disconnect()
        
        # Clear the screen/framebuffer when video stops (before standby)
        # Only clear if we're actually stopping (not just switching folders)
        if standby_hdmi:
            self.clear_display()
        
        # Put HDMI display in standby if requested (when no active folder)
        if standby_hdmi and self.hdmi.is_available():
            # Small delay to ensure video process is fully stopped and display is cleared
            time.sleep(1)
            self.logger.info("Putting HDMI display in standby...")
            if not self.hdmi.standby_hdmi():
                self.logger.warning("Failed to put HDMI display in standby")
            else:
                self.logger.info("HDMI display put in standby")
        
        self.current_folder = None
    
    def clear_display(self):
        """Clear the HDMI display/framebuffer to show blank screen"""
        try:
            self.logger.info("Clearing display...")
            
            # Method 1: Use fbset to blank the display (safe method)
            try:
                result = subprocess.run(
                    ['fbset', '-blank'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=2,
                    check=False
                )
                if result.returncode == 0:
                    self.logger.debug("Display cleared using fbset")
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            
            # Method 2: Use setterm to clear console (if available)
            try:
                subprocess.run(
                    ['setterm', '-blank', 'force', '-term', 'linux'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
            
            # Method 3: Clear framebuffer by writing black to /dev/fb0 (if accessible)
            if os.path.exists('/dev/fb0'):
                try:
                    # Get display resolution from fbset or use defaults
                    # Common Raspberry Pi resolutions: 1920x1080, 1280x720, 800x600
                    # Try to detect resolution, fallback to Full HD
                    width = 1920
                    height = 1080
                    
                    # Try to get actual resolution
                    try:
                        result = subprocess.run(
                            ['fbset', '-s'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=2,
                            text=True,
                            check=False
                        )
                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                if 'geometry' in line:
                                    parts = line.split()
                                    if len(parts) >= 3:
                                        width = int(parts[1])
                                        height = int(parts[2])
                                    break
                    except Exception:
                        pass
                    
                    # Calculate buffer size (width * height * bytes_per_pixel)
                    # Assume 32-bit color (RGBA) = 4 bytes per pixel
                    buffer_size = width * height * 4
                    
                    # Write black pixels to framebuffer
                    with open('/dev/fb0', 'wb') as fb:
                        fb.write(b'\x00' * min(buffer_size, 1920 * 1080 * 4))
                    
                    self.logger.debug(f"Display framebuffer cleared ({width}x{height})")
                    
                except (PermissionError, OSError) as e:
                    self.logger.debug(f"Could not clear framebuffer directly: {e}")
                except Exception as e:
                    self.logger.debug(f"Error clearing framebuffer: {e}")
            
            # Method 4: Fallback - use clear command for terminal
            try:
                subprocess.run(
                    ['clear'],
                    timeout=1,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
                
        except Exception as e:
            # Don't log errors for display clearing - it's not critical
            self.logger.debug(f"Could not clear display: {e}")
    
    def run(self):
        """Main loop"""
        self.logger.info("Starting video looper")
        
        # USB sync on boot (check for USB drives and sync if found)
        self.logger.info("Checking for USB drives and syncing if found...")
        try:
            self.usb_sync.sync_on_boot()
        except Exception as e:
            self.logger.warning(f"USB sync failed: {e}")
            # Continue even if USB sync fails
        
        # Initial time synchronization
        self.logger.info("Performing initial time synchronization...")
        if self.time_sync.sync_time():
            self.logger.info("Time synchronization successful")
        else:
            self.logger.warning("Time synchronization failed, continuing with system time")
        
        # Start background time synchronization
        self.time_sync.start_background_sync()
        
        current_folder = None
        
        while self.running:
            try:
                # Check for active folder
                active_folder_info = self.find_active_folder()
                
                if active_folder_info:
                    folder_path, video_files = active_folder_info
                    
                    # If we're playing a different folder, switch
                    if current_folder != folder_path:
                        self.logger.info(f"Switching to folder: {folder_path.name}")
                        self.stop_video(standby_hdmi=False)  # Don't standby during folder switch
                        if self.start_video(video_files, folder_path):
                            current_folder = folder_path
                        else:
                            current_folder = None
                else:
                    # No active folder - check if video is actually playing
                    if self.current_folder is not None or self.current_process is not None:
                        self.logger.info("No active folders, stopping video")
                        self.stop_video(standby_hdmi=True)  # Standby when no active folder
                        current_folder = None
                    # Also ensure HDMI is in standby even if we already stopped
                    elif self.hdmi.is_available():
                        # Double-check HDMI state and put to standby if needed
                        hdmi_state = self.hdmi.get_hdmi_power()
                        if hdmi_state == 1:
                            self.logger.info("No active folders and HDMI is still on, putting HDMI in standby")
                            self.hdmi.standby_hdmi()
                
                # Wait before checking again
                time.sleep(30)  # Check every 30 seconds
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)  # Wait longer on error
        
        self.stop_video(standby_hdmi=True)
        self.time_sync.stop_background_sync()
        self.logger.info("Video looper stopped")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Video Looper')
    parser.add_argument('--videos-path', default=None,
                       help='Path to videos directory (default: /home/looper/videos)')
    parser.add_argument('--log-file', default='/var/log/video_looper.log',
                       help='Log file path (default: /var/log/video_looper.log)')
    parser.add_argument('--test', action='store_true',
                       help='Test mode - show what would be played without starting VLC')
    parser.add_argument('--time-status', action='store_true',
                       help='Show time synchronization status')
    parser.add_argument('--sync-time', action='store_true',
                       help='Force time synchronization')
    parser.add_argument('--projector-test', action='store_true',
                       help='Test projector connection')
    parser.add_argument('--projector-start', action='store_true',
                       help='Start projector')
    parser.add_argument('--projector-stop', action='store_true',
                       help='Stop projector')
    parser.add_argument('--list-ports', action='store_true',
                       help='List available serial ports')
    parser.add_argument('--usb-sync', action='store_true',
                       help='Sync videos from USB drive')
    parser.add_argument('--usb-sync-test', action='store_true',
                       help='Test USB sync (show what would be synced without copying)')
    parser.add_argument('--usb-path', default=None,
                       help='Path to USB drive to sync from (optional, auto-detects if not specified)')
    
    args = parser.parse_args()
    
    looper = VideoLooper(args.videos_path, args.log_file)
    
    if args.test:
        # Test mode - just show what would be active
        active_folder_info = looper.find_active_folder()
        if active_folder_info:
            folder_path, video_files = active_folder_info
            print(f"Active folder: {folder_path.name}")
            print(f"Video files: {[f.name for f in video_files]}")
        else:
            print("No active folders found")
        return
    
    elif args.time_status:
        # Show time synchronization status
        status = looper.time_sync.get_time_status()
        print("Time Synchronization Status:")
        for key, value in status.items():
            print(f"  {key}: {value}")
        return
    
    elif args.sync_time:
        # Force time synchronization
        print("Forcing time synchronization...")
        if looper.time_sync.sync_time():
            print("✓ Time synchronization successful")
        else:
            print("✗ Time synchronization failed")
        return
    
    elif args.projector_test:
        # Test projector connection
        print("Testing projector connection...")
        if looper.projector.test_connection():
            print("✓ Projector connection test successful")
        else:
            print("✗ Projector connection test failed")
        return
    
    elif args.projector_start:
        # Start projector
        print("Starting projector...")
        if looper.projector.connect():
            if looper.projector.start_projector():
                print("✓ Projector started successfully")
            else:
                print("✗ Failed to start projector")
            looper.projector.disconnect()
        else:
            print("✗ Failed to connect to projector")
        return
    
    elif args.projector_stop:
        # Stop projector
        print("Stopping projector...")
        if looper.projector.connect():
            if looper.projector.stop_projector():
                print("✓ Projector stopped successfully")
            else:
                print("✗ Failed to stop projector")
            looper.projector.disconnect()
        else:
            print("✗ Failed to connect to projector")
        return
    
    elif args.list_ports:
        # List available serial ports
        print("Available serial ports:")
        ports = looper.projector.get_available_ports()
        for port in ports:
            print(f"  {port['device']}: {port['description']} ({port['manufacturer']})")
        return
    
    elif args.usb_sync_test:
        # Test USB sync (scanning only, no copying)
        print("Testing USB sync (scanning only, no copying)...")
        print(f"\nScanning USB drives...")
        usb_mounts = looper.usb_sync.find_usb_drives()
        print(f"Found {len(usb_mounts)} potential USB drive(s):")
        
        usb_folders_all = {}
        for mount in usb_mounts:
            print(f"  - {mount}")
            valid_folders = looper.usb_sync.get_valid_folders(mount)
            print(f"    Valid video folders: {len(valid_folders)}")
            for folder_name in valid_folders.keys():
                print(f"      - {folder_name}")
                usb_folders_all[folder_name] = mount
        
        print(f"\nLocal video folders in {looper.videos_path}:")
        local_folders = looper.usb_sync.get_valid_folders(looper.videos_path)
        print(f"  Found {len(local_folders)} valid folder(s):")
        for folder_name in local_folders.keys():
            print(f"    - {folder_name}")
        
        if usb_mounts and usb_folders_all:
            print(f"\nIf synced, would:")
            for folder_name in usb_folders_all.keys():
                if folder_name not in local_folders:
                    print(f"  - Copy folder: {folder_name}")
                else:
                    print(f"  - Update folder: {folder_name}")
            for folder_name in local_folders.keys():
                if folder_name not in usb_folders_all:
                    print(f"  - Delete folder: {folder_name}")
        return
    
    elif args.usb_sync:
        # Manual USB sync
        print("Syncing from USB drive...")
        try:
            if args.usb_path:
                print(f"Using USB path: {args.usb_path}")
                success = looper.usb_sync.sync_usb_to_local(Path(args.usb_path))
                if success:
                    print("✓ USB sync completed successfully")
                else:
                    print("✗ USB sync completed with errors (check logs)")
            else:
                success = looper.usb_sync.sync_on_boot()
                if success:
                    print("✓ USB sync completed successfully")
                else:
                    print("✗ No USB drives with valid video folders found")
        except Exception as e:
            print(f"✗ USB sync failed: {e}")
            import traceback
            traceback.print_exc()
        return
    
    looper.run()

if __name__ == '__main__':
    main()
