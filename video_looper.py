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
from keyboard_monitor import KeyboardMonitor
from constants import (
    DEFAULT_VIDEOS_PATH, DEFAULT_LOG_FILE, VIDEO_EXTENSIONS,
    PROJECTOR_CONFIG_FILES, FOLDER_NAME_PATTERN, DATE_FORMAT, TIME_FORMAT,
    CHECK_INTERVAL, HDMI_WAKE_DELAY, TEST_PLAY_DURATION, TEST_PAUSE_DURATION
)
import threading

class VideoLooper:
    def __init__(self, videos_path=None, log_file=None):
        # Use fixed paths for looper user
        if videos_path is None:
            videos_path = DEFAULT_VIDEOS_PATH
        if log_file is None:
            log_file = DEFAULT_LOG_FILE
            
        self.videos_path = Path(videos_path)
        self.log_file = log_file
        self.current_process = None
        self.current_folder = None
        self.running = True
        self.test_mode_active = False
        self.keyboard_monitor = None
        
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
    
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.WARNING,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.running = False
        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
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
        match = re.match(FOLDER_NAME_PATTERN, folder_name)
        
        if not match:
            return None
        
        try:
            start_date = datetime.strptime(match.group(1), DATE_FORMAT).date()
            end_date = datetime.strptime(match.group(2), DATE_FORMAT).date()
            start_time = datetime.strptime(match.group(3), TIME_FORMAT).time()
            end_time = datetime.strptime(match.group(4), TIME_FORMAT).time()
            
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
        video_files = [
            f for f in folder_path.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
        return sorted(video_files)
    
    def has_projector_config(self, folder_path):
        """Check if folder has projector configuration file"""
        for config_file in PROJECTOR_CONFIG_FILES:
            config_path = folder_path / config_file
            if config_path.exists():
                return True
        
        return False
    
    def load_projector_config(self, folder_path):
        """Load projector configuration from folder"""
        for config_file in PROJECTOR_CONFIG_FILES:
            config_path = folder_path / config_file
            if config_path.exists():
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
                time.sleep(start_delay)
                return True
        except (ValueError, TypeError):
            pass
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
            return None
        
        # If multiple folders are active, use the one with the most recent start date
        active_folders.sort(key=lambda x: self.parse_folder_name(x[0].name)['start_date'], reverse=True)
        
        return active_folders[0]
    
    def get_all_valid_folders(self):
        """
        Get all valid video folders regardless of schedule
        Returns list of all folders matching naming pattern with video files
        """
        if not self.videos_path.exists():
            return []
        
        valid_folders = []
        
        for folder_path in self.videos_path.iterdir():
            if folder_path.is_dir():
                # Check if folder name matches pattern
                schedule = self.parse_folder_name(folder_path.name)
                if schedule:
                    video_files = self.get_video_files(folder_path)
                    if video_files:
                        valid_folders.append((folder_path, video_files))
        
        # Sort by start date (most recent first)
        valid_folders.sort(key=lambda x: self.parse_folder_name(x[0].name)['start_date'], reverse=True)
        
        return valid_folders
    
    def start_video(self, video_files, folder_path):
        """Start VLC with video files in loop mode and control projector"""
        if not video_files:
            self.logger.error("No video files provided")
            return False
        
        if self.hdmi.is_available():
            if self.hdmi.wake_hdmi():
                time.sleep(HDMI_WAKE_DELAY)
        
        if self.has_projector_config(folder_path):
            self.load_projector_config(folder_path)
            if self.projector.config.get('enable_projector', False):
                if not self.projector.connect():
                    self.logger.error("Failed to connect to projector")
                elif not self.projector.start_projector():
                    self.logger.error("Failed to start projector")
            self.handle_video_start_delay(folder_path)
        
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
            self.current_process = subprocess.Popen(
                vlc_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.current_folder = folder_path
            return True
        except Exception as e:
            self.logger.error(f"Failed to start VLC: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def start_video_timed(self, video_files, folder_path, duration):
        """
        Start VLC with video files for a limited duration (for test mode)
        Args:
            video_files: List of video file paths
            folder_path: Path to folder containing videos
            duration: Duration in seconds to play
        Returns:
            subprocess.Popen object if successful, None otherwise
        """
        if not video_files:
            return None
        
        if self.has_projector_config(folder_path):
            self.load_projector_config(folder_path)
            if self.projector.config.get('enable_projector', False):
                if not self.projector.connect():
                    self.logger.error("Failed to connect to projector")
                elif not self.projector.start_projector():
                    self.logger.error("Failed to start projector")
        
        # Create VLC command without --loop for timed playback
        vlc_cmd = [
            'cvlc',
            '--intf', 'dummy',
            '--fullscreen',
            '--no-osd',
            '--no-audio',
            '--quiet',
            '--run-time', str(duration),  # Limit playback duration
        ]
        
        # Add all video files to the command
        vlc_cmd.extend([str(f) for f in video_files])
        
        try:
            process = subprocess.Popen(
                vlc_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return process
        except Exception as e:
            self.logger.error(f"Failed to start timed video: {e}")
            return None
    
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
            except subprocess.TimeoutExpired:
                self.current_process.kill()
                self.current_process.wait()
            except Exception as e:
                self.logger.error(f"Error stopping video: {e}")
            finally:
                self.current_process = None
        
        if self.current_folder and self.has_projector_config(self.current_folder):
            if self.projector.config.get('enable_projector', False):
                if not self.projector.stop_projector():
                    self.logger.error("Failed to stop projector")
                self.projector.disconnect()
        
        if standby_hdmi:
            self.clear_display()
            if self.hdmi.is_available():
                time.sleep(1)
                if not self.hdmi.standby_hdmi():
                    self.logger.error("Failed to put HDMI in standby")
        
        self.current_folder = None
    
    def _on_test_key_triggered(self):
        """Callback when Ctrl+F1 is detected"""
        if self.test_mode_active:
            return
        
        # Start test mode in separate thread to avoid blocking
        test_thread = threading.Thread(target=self.run_test_mode, daemon=True)
        test_thread.start()
    
    def run_test_mode(self):
        """
        Run test mode: play all valid folders for 1 minute each with 30 second pauses
        """
        self.test_mode_active = True
        
        # Get all valid folders
        all_folders = self.get_all_valid_folders()
        
        if not all_folders:
            self.logger.error("No valid video folders found for test mode")
            self.test_mode_active = False
            return
        
        self.logger.error(f"Starting test mode: {len(all_folders)} folder(s) to test")
        print(f"\n=== TEST MODE STARTED ===", flush=True)
        print(f"Testing {len(all_folders)} folder(s), 1 minute each with 30 second pauses\n", flush=True)
        
        # Interrupt current playback if active
        if self.current_process:
            self.stop_video(standby_hdmi=False)
        
        # Wake HDMI display
        if self.hdmi.is_available():
            self.hdmi.wake_hdmi()
            time.sleep(HDMI_WAKE_DELAY)
        
        # Test each folder
        for idx, (folder_path, video_files) in enumerate(all_folders, 1):
            folder_name = folder_path.name
            self.logger.error(f"Testing folder {idx}/{len(all_folders)}: {folder_name}")
            
            # Print folder name to terminal
            print(f"\n[{idx}/{len(all_folders)}] Testing folder: {folder_name}", flush=True)
            
            # Load projector config if available
            if self.has_projector_config(folder_path):
                self.load_projector_config(folder_path)
                if self.projector.config.get('enable_projector', False):
                    if not self.projector.connect():
                        self.logger.error("Failed to connect to projector")
                    elif not self.projector.start_projector():
                        self.logger.error("Failed to start projector")
            
            # Start video playback for TEST_PLAY_DURATION
            process = self.start_video_timed(video_files, folder_path, TEST_PLAY_DURATION)
            
            if process:
                # Wait for duration or until process ends
                try:
                    process.wait(timeout=TEST_PLAY_DURATION + 5)
                except subprocess.TimeoutExpired:
                    # Kill if still running after duration
                    process.kill()
                    process.wait()
                except Exception as e:
                    self.logger.error(f"Error waiting for test video: {e}")
                    try:
                        process.kill()
                        process.wait()
                    except Exception:
                        pass
            
            # Stop projector if was started
            if self.has_projector_config(folder_path):
                if self.projector.config.get('enable_projector', False):
                    if not self.projector.stop_projector():
                        self.logger.error("Failed to stop projector")
                    self.projector.disconnect()
            
            # Pause between folders (except after last folder)
            if idx < len(all_folders):
                time.sleep(TEST_PAUSE_DURATION)
        
        # Cleanup after test mode
        self.clear_display()
        if self.hdmi.is_available():
            time.sleep(1)
            self.hdmi.standby_hdmi()
        
        print(f"\n=== TEST MODE COMPLETED ===\n", flush=True)
        self.logger.error("Test mode completed")
        self.test_mode_active = False
    
    def clear_display(self):
        """Clear the HDMI display/framebuffer to show blank screen"""
        try:
            result = subprocess.run(
                ['fbset', '-blank'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
                check=False
            )
            if result.returncode == 0:
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
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
        
        if os.path.exists('/dev/fb0'):
            try:
                width, height = 1920, 1080
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
                
                buffer_size = width * height * 4
                with open('/dev/fb0', 'wb') as fb:
                    fb.write(b'\x00' * min(buffer_size, 1920 * 1080 * 4))
            except Exception:
                pass
    
    def run(self):
        """Main loop"""
        try:
            self.usb_sync.sync_on_boot()
        except Exception:
            pass
        
        self.time_sync.sync_time()
        self.time_sync.start_background_sync()
        
        # Initialize and start keyboard monitor
        try:
            self.keyboard_monitor = KeyboardMonitor(self._on_test_key_triggered, self.log_file)
            if self.keyboard_monitor.is_available():
                self.keyboard_monitor.start()
        except Exception as e:
            self.logger.error(f"Failed to start keyboard monitor: {e}")
        
        current_folder = None
        while self.running:
            try:
                # Skip normal playback if test mode is active
                if self.test_mode_active:
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                active_folder_info = self.find_active_folder()
                
                if active_folder_info:
                    folder_path, video_files = active_folder_info
                    if current_folder != folder_path:
                        self.stop_video(standby_hdmi=False)
                        if self.start_video(video_files, folder_path):
                            current_folder = folder_path
                        else:
                            current_folder = None
                else:
                    if self.current_folder is not None or self.current_process is not None:
                        self.stop_video(standby_hdmi=True)
                        current_folder = None
                    elif self.hdmi.is_available():
                        hdmi_state = self.hdmi.get_hdmi_power()
                        if hdmi_state == 1:
                            self.hdmi.standby_hdmi()
                
                time.sleep(CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)
        
        # Cleanup
        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
        self.stop_video(standby_hdmi=True)
        self.time_sync.stop_background_sync()

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
