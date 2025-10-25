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

class VideoLooper:
    def __init__(self, videos_path="/home/pi/videos", log_file="/var/log/video_looper.log"):
        self.videos_path = Path(videos_path)
        self.log_file = log_file
        self.current_process = None
        self.running = True
        
        # Setup logging
        self.setup_logging()
        
        # Initialize time synchronization
        self.time_sync = TimeSyncManager(log_file)
        
        # Initialize projector controller
        self.projector = ProjectorController(log_file)
        
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
        self.stop_video()
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
        if not (schedule['start_time'] <= current_time <= schedule['end_time']):
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
        if start_delay > 0:
            self.logger.info(f"Video start delay configured: {start_delay} seconds")
            time.sleep(start_delay)
            return True
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
        
        # Create VLC command
        vlc_cmd = [
            'vlc',
            '--intf', 'dummy',  # No GUI
            '--no-video-title-show',  # Don't show video title
            '--fullscreen',  # Fullscreen mode
            '--loop',  # Loop the playlist
            '--no-audio-display',  # Don't show audio info
            '--quiet',  # Reduce output
            '--no-osd',  # No on-screen display
        ]
        
        # Add all video files to the command
        vlc_cmd.extend([str(f) for f in video_files])
        
        try:
            self.logger.info(f"Starting VLC with {len(video_files)} video files")
            self.current_process = subprocess.Popen(
                vlc_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to start VLC: {e}")
            return False
    
    def stop_video(self):
        """Stop the current video playback and projector"""
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
        
        # Stop projector if enabled
        if self.projector.config.get('enable_projector', False):
            self.logger.info("Stopping projector...")
            if not self.projector.stop_projector():
                self.logger.warning("Failed to stop projector")
            self.projector.disconnect()
    
    def run(self):
        """Main loop"""
        self.logger.info("Starting video looper")
        
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
                        self.stop_video()
                        if self.start_video(video_files, folder_path):
                            current_folder = folder_path
                        else:
                            current_folder = None
                else:
                    # No active folder, stop video if playing
                    if current_folder:
                        self.logger.info("No active folders, stopping video")
                        self.stop_video()
                        current_folder = None
                
                # Wait before checking again
                time.sleep(30)  # Check every 30 seconds
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)  # Wait longer on error
        
        self.stop_video()
        self.time_sync.stop_background_sync()
        self.logger.info("Video looper stopped")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Video Looper')
    parser.add_argument('--videos-path', default='/home/pi/videos',
                       help='Path to videos directory (default: /home/pi/videos)')
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
    
    looper.run()

if __name__ == '__main__':
    main()
