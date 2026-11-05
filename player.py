#!/usr/bin/env python3
"""Plays a folder's videos with VLC, and controls the display and projector around that"""

import logging
import os
import subprocess
import time
import time_entry
from constants import HDMI_WAKE_DELAY, PROJECTOR_CONFIG_FILES
from hdmi_controller import STATE_ON


class Player:
    def __init__(self, hdmi, projector):
        self.logger = logging.getLogger(__name__)
        self.hdmi = hdmi
        self.projector = projector
        self.current_process = None
        self.current_folder = None

    def is_playing(self):
        """Check whether VLC is running"""
        return self.current_process is not None and self.current_process.poll() is None

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
    
    def wake_display(self):
        """Wake the HDMI display if it was last told to be off, and give it time to come on"""
        if self.hdmi.is_available() and self.hdmi.last_state != STATE_ON:
            if self.hdmi.wake_hdmi():
                time.sleep(HDMI_WAKE_DELAY)
    
    def start_video(self, video_files, folder_path, duration=None):
        """
        Start VLC and the projector for a folder's videos
        Args:
            video_files: List of video file paths
            folder_path: Path to folder containing videos
            duration: Seconds to play for (demo mode), or None to loop until stopped
        Returns:
            bool: True if started successfully, False otherwise
        """
        if not video_files:
            self.logger.error("No video files provided")
            return False

        self.wake_display()

        if self.has_projector_config(folder_path):
            self.load_projector_config(folder_path)
            if self.projector.config.get('enable_projector', False):
                if not self.projector.connect():
                    self.logger.error("Failed to connect to projector")
                elif not self.projector.start_projector():
                    self.logger.error("Failed to start projector")
            self.handle_video_start_delay(folder_path)

        # Time entry may have started during the delays above
        if time_entry.is_active():
            return False

        # Create VLC command using cvlc (command-line VLC)
        vlc_cmd = [
            'cvlc',
            '--intf', 'dummy',  # No GUI
            '--fullscreen',  # Fullscreen mode
            *(['--run-time', str(duration)] if duration else ['--loop']),
            '--no-osd',  # No on-screen display
            '--no-audio',  # no audio
            '--quiet',  # Reduce output
            *[str(f) for f in video_files],
        ]

        try:
            self.current_process = subprocess.Popen(
                vlc_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.current_folder = folder_path
            return True
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.error(f"Failed to start VLC: {e}")
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
            except subprocess.TimeoutExpired:
                self.current_process.kill()
                self.current_process.wait()
            except (OSError, subprocess.SubprocessError) as e:
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
                self.hdmi.standby_hdmi()

        self.current_folder = None
    
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
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                
                buffer_size = width * height * 4
                with open('/dev/fb0', 'wb') as fb:
                    fb.write(b'\x00' * min(buffer_size, 1920 * 1080 * 4))
            except OSError:
                pass
