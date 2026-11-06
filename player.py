#!/usr/bin/env python3
"""Plays a folder's videos with VLC, and controls the display and projector around that"""

import glob
import logging
import os
import subprocess
import time
import time_entry
from constants import (
    AUDIO_CONFIG_FILE, HDMI_AUDIO_DEVICE, HDMI_STATUS_FILES, HDMI_WAKE_DELAY, PROJECTOR_CONFIG_FILES
)
from hdmi_controller import STATE_ON

logger = logging.getLogger(__name__)


def audio_enabled():
    """Check if videos should play with sound. A missing or damaged settings file means no."""
    try:
        with open(AUDIO_CONFIG_FILE, encoding='utf-8') as f:
            return f.read().strip() == 'enabled=true'
    except (OSError, UnicodeError):
        return False


def set_audio_enabled(enabled):
    """Save the audio setting. Returns True if it was saved."""
    temp_file = f"{AUDIO_CONFIG_FILE}.tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(f"enabled={'true' if enabled else 'false'}\n")
        os.replace(temp_file, AUDIO_CONFIG_FILE)
        return True
    except OSError as e:
        logger.error(f"Could not save the audio setting: {e}")
        return False


def audio_device():
    """The sound device of the first HDMI port with a display connected, otherwise HDMI 0"""
    for index in (0, 1):
        for status_file in glob.glob(HDMI_STATUS_FILES.format(port=index + 1)):
            try:
                with open(status_file, encoding='utf-8') as f:
                    if f.read().strip() == 'connected':
                        return HDMI_AUDIO_DEVICE.format(index=index)
            except OSError:
                pass
    return HDMI_AUDIO_DEVICE.format(index=0)


class Player:
    def __init__(self, hdmi, projector):
        self.logger = logging.getLogger(__name__)
        self.hdmi = hdmi
        self.projector = projector
        self.current_process = None
        self.current_folder = None
        self.projector_on = False  # This process sent the start command, and no stop since

    def is_playing(self):
        """Check whether VLC is running"""
        return self.current_process is not None and self.current_process.poll() is None

    def wait_for_vlc_to_exit(self, timeout=15):
        """Wait until no VLC is running on the system, including one the service started"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if subprocess.run(['pgrep', '-x', 'vlc'], stdout=subprocess.DEVNULL, timeout=5).returncode != 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                return False
            time.sleep(0.5)
        self.logger.warning("VLC is still running; the demo may not get the display")
        return False

    def has_projector_config(self, folder_path):
        """Check if folder has projector configuration file"""
        for config_file in PROJECTOR_CONFIG_FILES:
            config_path = folder_path / config_file
            if config_path.exists():
                return True
        
        return False
    
    def load_projector_config(self, folder_path):
        """Load a folder's projector settings, or the defaults if it has no settings file"""
        for config_file in PROJECTOR_CONFIG_FILES:
            config_path = folder_path / config_file
            if config_path.exists():
                return self.projector.load_config_from_file(str(config_path))
        
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
    
    def _start_projector(self, folder_path):
        """
        Start the projector for a folder, and wait for it if the settings say so.
        If it's already on with the same settings it's left alone, since many
        projectors ignore a start command while cooling down from a stop.
        """
        previous_config = self.projector.config
        self.load_projector_config(folder_path)
        new_config = self.projector.config

        if self.projector_on:
            if new_config == previous_config:
                return
            self.projector.config = previous_config
            self.stop_projector()
            self.projector.config = new_config

        if new_config.get('enable_projector', False):
            if not self.projector.connect():
                self.logger.error("Failed to connect to projector")
            elif not self.projector.start_projector():
                self.logger.error("Failed to start projector")
            else:
                self.projector_on = True
        self.handle_video_start_delay(folder_path)

    def stop_projector(self):
        """Stop the projector, if this process started it"""
        if not self.projector_on:
            return
        self.projector_on = False
        if not self.projector.stop_projector():
            self.logger.error("Failed to stop projector")
        self.projector.disconnect()

    def release_projector(self):
        """Close the serial port but leave the projector on, for the service to take over"""
        self.projector_on = False
        self.projector.disconnect()

    def wake_display(self):
        """Wake the HDMI display if it was last told to be off, and give it time to come on"""
        if self.hdmi.is_available() and self.hdmi.last_state != STATE_ON:
            if self.hdmi.wake_hdmi():
                time.sleep(HDMI_WAKE_DELAY)

    def start_video(self, video_files, folder_path, duration=None, ignore_hold=False):
        """
        Start VLC and the projector for a folder's videos
        Args:
            video_files: List of video file paths
            folder_path: Path to folder containing videos
            duration: Seconds to play for (demo mode), or None to loop until stopped
            ignore_hold: Start even during a menu hold, for the demo that holds it
        Returns:
            bool: True if started successfully, False otherwise
        """
        if not video_files:
            self.logger.error("No video files provided")
            return False

        self.wake_display()

        self._start_projector(folder_path)

        # The menu may have taken the screen during the delays above
        if not ignore_hold and time_entry.is_active():
            return False

        # Create VLC command using cvlc (command-line VLC)
        vlc_cmd = [
            'cvlc',
            '--intf', 'dummy',  # No GUI
            '--fullscreen',  # Fullscreen mode
            *(['--run-time', str(duration)] if duration else ['--loop']),
            '--no-osd',  # No on-screen display
            *(['--aout=alsa', f'--alsa-audio-device={audio_device()}'] if audio_enabled() else ['--no-audio']),
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
        Stop the current video playback. The projector stays on: use stop_projector
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
