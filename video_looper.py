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
import select
import termios
import tty
import fcntl
import calendar
from datetime import datetime
from pathlib import Path
import signal
from time_sync import TimeSyncManager
from projector_controller import ProjectorController
from hdmi_controller import HDMIController, STATE_ON
from usb_sync import USBSync
from console import show_on_console
from constants import (
    DEFAULT_VIDEOS_PATH, VIDEO_EXTENSIONS,
    PROJECTOR_CONFIG_FILES, FOLDER_NAME_PATTERN, DATE_FORMAT, TIME_FORMAT,
    CHECK_INTERVAL, HDMI_WAKE_DELAY, TIME_ENTRY_LOCK_FILE,
    TIME_SET_REQUEST_FILE, TIME_SET_RESULT_FILE, TIME_SET_TIMEOUT
)

class VideoLooper:
    def __init__(self, videos_path=None):
        # Use fixed paths for looper user
        if videos_path is None:
            videos_path = DEFAULT_VIDEOS_PATH
            
        self.videos_path = Path(videos_path)
        self.current_process = None
        self.current_folder = None
        self.running = True
        
        # Setup logging
        self.setup_logging()
        
        # Initialize time synchronization
        self.time_sync = TimeSyncManager()
        
        # Initialize projector controller
        self.projector = ProjectorController()
        
        # Initialize HDMI controller
        self.hdmi = HDMIController()
        
        # Initialize USB sync
        self.usb_sync = USBSync(str(self.videos_path))
        
        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def setup_logging(self):
        """Setup logging configuration - minimal logging to reduce SD card wear"""
        logging.basicConfig(
            level=logging.WARNING,  # Warnings and errors only
            format='%(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stderr)  # No file writes to reduce SD card wear
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.running = False
        self.stop_video(standby_hdmi=True)
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
        """Get all video files from a folder, ignoring hidden files (starting with '.')"""
        video_files = [
            f for f in folder_path.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and not f.name.startswith('.')
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
        Get all valid video folders regardless of schedule, sorted chronologically
        Returns list of tuples: (folder_path, video_files)
        Ignores folders and files that start with '.'
        """
        if not self.videos_path.exists():
            return []
        
        valid_folders = []
        
        for folder_path in self.videos_path.iterdir():
            if folder_path.is_dir():
                # Skip hidden folders (starting with '.')
                if folder_path.name.startswith('.'):
                    continue
                
                # Check if folder name matches pattern
                schedule = self.parse_folder_name(folder_path.name)
                if schedule:
                    video_files = self.get_video_files(folder_path)
                    if video_files:
                        valid_folders.append((folder_path, video_files))
        
        # Sort by start date (ascending - chronological order)
        valid_folders.sort(key=lambda x: self.parse_folder_name(x[0].name)['start_date'])
        
        return valid_folders
    
    def display_folder_info_on_screen(self):
        """Display folder information on HDMI screen"""
        try:
            # Get all valid folders
            all_folders = self.get_all_valid_folders()
            
            # Prepare text content
            lines = []
            lines.append("")
            lines.append("Raspberry Pi Video Looper - System Information")
            lines.append("=" * 60)
            lines.append("")
            
            now = datetime.now()
            current_time = now.strftime('%Y-%m-%d %H:%M:%S')
            lines.append(f"Current Date/Time: {current_time}")
            lines.append("")
            
            if not all_folders:
                lines.append("No valid video loop folders found.")
            else:
                lines.append(f"Found {len(all_folders)} valid loop folder(s) (chronological order):")
                lines.append("")
                
                for idx, (folder_path, video_files) in enumerate(all_folders, 1):
                    folder_name = folder_path.name
                    schedule = self.parse_folder_name(folder_name)
                    
                    lines.append(f"[{idx}] {folder_name}")
                    
                    if schedule:
                        start_date = schedule['start_date'].strftime('%Y-%m-%d')
                        end_date = schedule['end_date'].strftime('%Y-%m-%d')
                        start_time = schedule['start_time'].strftime('%H:%M')
                        end_time = schedule['end_time'].strftime('%H:%M')
                        lines.append(f"     Schedule: {start_date} to {end_date}, {start_time} to {end_time}")
                    else:
                        lines.append("     Schedule: Unknown")
                    
                    lines.append(f"     Videos ({len(video_files)} file(s)):")
                    for video_file in video_files:
                        try:
                            file_size = video_file.stat().st_size
                            size_mb = file_size / (1024 * 1024)
                            size_str = f"{size_mb:.1f} MB"
                        except OSError:
                            size_str = "unknown size"
                        lines.append(f"       - {video_file.name} ({size_str})")
                    
                    lines.append("")
            
            lines.append("=" * 60)
            lines.append("")
            
            # Display on console/TTY
            text = "\n".join(lines)
            print(text, flush=True)
            
            # tty1 is the main console, which usually shows on HDMI
            if not show_on_console(text):
                self.logger.error("Could not write to TTY1")

            # Keep the information visible for 10 seconds before showing menu
            time.sleep(10)
            
            # Show boot menu after folder info
            return self.display_boot_menu()
            
        except Exception as e:
            self.logger.error(f"Error displaying folder info: {e}")
            return None
    
    def _setup_terminal_input(self):
        """Setup terminal for raw input"""
        try:
            if sys.stdin.isatty():
                self.old_settings = termios.tcgetattr(sys.stdin)
                fd = sys.stdin.fileno()
                tty.setraw(fd)
                # The menus draw on this same terminal, and setraw also turns off
                # output processing, which makes each "\n" continue on the same column.
                attrs = termios.tcgetattr(fd)
                attrs[1] |= termios.OPOST | termios.ONLCR
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
                return True
        except (termios.error, OSError, ValueError) as e:
            self.logger.warning(f"Could not set up terminal input: {e}")
        return False
    
    def _restore_terminal_input(self):
        """Restore terminal settings"""
        try:
            if hasattr(self, 'old_settings') and sys.stdin.isatty():
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
        except (termios.error, OSError, ValueError) as e:
            self.logger.warning(f"Could not restore terminal settings: {e}")
    
    def get_char_blocking(self, timeout=None):
        """Get a single character with optional timeout - blocking"""
        try:
            if timeout:
                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if not ready:
                    return None
            return sys.stdin.read(1)
        except (OSError, ValueError):
            return None
    
    def display_boot_menu(self):
        """Display boot menu UI and handle user selection - stable version"""
        try:
            menu_timeout = 20  # seconds to wait for input
            start_time = time.time()
            last_countdown_update = 0
            
            # Setup terminal for raw input
            terminal_setup = self._setup_terminal_input()
            
            try:
                # Show menu once
                self._show_menu_screen(menu_timeout)
                
                # Wait for input with periodic countdown updates
                while True:
                    elapsed = time.time() - start_time
                    remaining = int(menu_timeout - elapsed)
                    
                    # Update countdown only once per second to avoid flickering
                    if int(time.time()) != int(last_countdown_update):
                        self._show_menu_screen(remaining)
                        last_countdown_update = time.time()
                    
                    # Check timeout
                    if elapsed >= menu_timeout:
                        self._restore_terminal_input()
                        return None  # Timeout, continue normal operation
                    
                    # Wait for input with 1 second timeout
                    char = self.get_char_blocking(timeout=1.0)
                    
                    if char:
                        # Stop countdown immediately
                        self._restore_terminal_input()
                        
                        # Process selection
                        if char == '1':
                            self._show_feedback("Option 1: Starting Demo Mode...")
                            time.sleep(0.5)
                            return 'demo'
                        elif char == '2':
                            self._show_feedback("Option 2: Setting RTC Time...")
                            time.sleep(0.5)
                            self.handle_manual_time_setting()
                            return None
                        elif char == '\n' or char == '\r':
                            return None  # Enter pressed, continue
                        else:
                            # Invalid key - show error and restart
                            self._show_feedback(f"Invalid option: {char}. Press 1, 2, or Enter...")
                            time.sleep(1.5)
                            start_time = time.time()  # Reset timer
                            last_countdown_update = 0
                            self._show_menu_screen(menu_timeout)
                            terminal_setup = self._setup_terminal_input()
                            
            finally:
                self._restore_terminal_input()
                
        except Exception as e:
            self.logger.error(f"Error in boot menu: {e}")
            self._restore_terminal_input()
            return None
    
    def _show_menu_screen(self, remaining=None):
        """Display menu screen without flickering"""
        lines = [
            "",
            "=" * 60,
            "Video Looper - Boot Menu",
            "=" * 60,
            "",
            "Select an option:",
            "",
            "  1. Start Demo Mode",
            "  2. Set RTC Time",
            "",
            "  Press 1, 2, or Enter to continue...",
            "",
        ]
        if remaining is not None and remaining > 0:
            lines.append(f"  Auto-continuing in {remaining} second(s)...")
        elif remaining is not None:
            lines.append("  Auto-continuing...")
        show_on_console("\n".join(lines) + "\n\n")
    
    def _show_feedback(self, message):
        """Show feedback message"""
        show_on_console("Video Looper - Boot Menu\n" + "=" * 60 + f"\n\n{message}\n")
    
    def _get_numeric_input(self, prompt_text, min_value, max_value, timeout=60):
        """Get numeric input with validation - stable version"""
        start_time = time.time()
        input_buffer = ""
        terminal_setup = self._setup_terminal_input()
        
        try:
            # Show prompt once
            self._show_numeric_prompt(prompt_text, input_buffer)
            
            while time.time() - start_time < timeout:
                # Read character with timeout
                char = self.get_char_blocking(timeout=0.5)
                
                if char is None:
                    # Timeout - update display occasionally
                    if int(time.time()) % 2 == 0:  # Update every 2 seconds
                        self._show_numeric_prompt(prompt_text, input_buffer)
                    continue
                
                if char == '\n' or char == '\r':
                    # Enter pressed
                    if input_buffer:
                        try:
                            value = int(input_buffer)
                            if min_value <= value <= max_value:
                                self._show_numeric_prompt(prompt_text, input_buffer, f"✓ Accepted: {value}")
                                time.sleep(0.5)
                                return value
                            else:
                                # Invalid range
                                self._show_numeric_prompt(prompt_text, "", f"✗ Error: Must be {min_value}-{max_value}. Press Enter...")
                                # Wait for Enter
                                while True:
                                    char = self.get_char_blocking(timeout=1.0)
                                    if char == '\n' or char == '\r':
                                        break
                                    if time.time() - start_time >= timeout:
                                        return None
                                input_buffer = ""
                                start_time = time.time()
                                self._show_numeric_prompt(prompt_text, input_buffer)
                        except ValueError:
                            input_buffer = ""
                            self._show_numeric_prompt(prompt_text, input_buffer)
                    else:
                        return None
                elif char == '\x7f' or char == '\b' or char == '\x08':  # Backspace
                    input_buffer = input_buffer[:-1] if input_buffer else ""
                    self._show_numeric_prompt(prompt_text, input_buffer)
                elif char.isdigit():
                    input_buffer += char
                    self._show_numeric_prompt(prompt_text, input_buffer)
                    # Auto-submit if we have enough digits and it's valid
                    if len(input_buffer) >= len(str(max_value)):
                        try:
                            value = int(input_buffer)
                            if min_value <= value <= max_value:
                                self._show_numeric_prompt(prompt_text, input_buffer, f"✓ Auto-accepted: {value}")
                                time.sleep(0.5)
                                return value
                        except ValueError:
                            pass
                elif char == '\x03':  # Ctrl+C
                    return None
            
            return None
        finally:
            self._restore_terminal_input()
    
    def _show_numeric_prompt(self, prompt_text, input_buffer, status=""):
        """Show numeric input prompt"""
        text = prompt_text
        if input_buffer:
            text += f"\n\nInput: {input_buffer}"
        if status:
            text += f"\n{status}"
        show_on_console(text)
    
    def _acquire_time_entry_hold(self):
        """
        Tell the looper service to hold the video while the time is being entered.
        Uses a file lock, which the kernel releases even if this process crashes.
        Returns the open lock file (close it to release), or None if it can't be taken.
        """
        try:
            lock_file = open(TIME_ENTRY_LOCK_FILE, 'a')
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            return lock_file
        except OSError as e:
            self.logger.error(f"Could not hold video during time entry: {e}")
            return None

    def is_time_entry_active(self):
        """Check whether the boot menu currently holds the time entry lock"""
        try:
            with open(TIME_ENTRY_LOCK_FILE, 'a') as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
        except OSError:
            return False

    def _write_file_atomic(self, path, text):
        """Write a small file so a reader never sees it half-written"""
        temp_path = f"{path}.tmp"
        with open(temp_path, 'w') as f:
            f.write(text)
        os.replace(temp_path, path)

    def _remove_file(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass

    def _request_time_set(self, time_str):
        """
        Menu side: ask the service to set the clock, since only it has permission.
        Returns True once the service confirms the system clock and RTC are both set.
        """
        self._remove_file(TIME_SET_RESULT_FILE)
        try:
            self._write_file_atomic(TIME_SET_REQUEST_FILE, time_str)
        except OSError as e:
            self.logger.error(f"Could not send time request: {e}")
            return False

        deadline = time.monotonic() + TIME_SET_TIMEOUT
        while time.monotonic() < deadline:
            try:
                with open(TIME_SET_RESULT_FILE) as f:
                    result = f.read().strip()
                self._remove_file(TIME_SET_RESULT_FILE)
                return result == 'ok'
            except OSError:
                time.sleep(0.2)

        # Service isn't answering: don't leave a request that could apply later
        self._remove_file(TIME_SET_REQUEST_FILE)
        self.logger.error("Video looper service did not answer the time request")
        return False

    def _process_time_request(self):
        """Service side: set the clock if the menu has asked for it"""
        try:
            # /dev/shm is writable by every user, so only accept our own user's requests
            if os.stat(TIME_SET_REQUEST_FILE).st_uid != os.getuid():
                return
            with open(TIME_SET_REQUEST_FILE) as f:
                time_str = f.read().strip()
        except OSError:
            return
        self._remove_file(TIME_SET_REQUEST_FILE)

        success = self.time_sync.set_time_manually(time_str)
        try:
            self._write_file_atomic(TIME_SET_RESULT_FILE, 'ok' if success else 'failed')
        except OSError as e:
            self.logger.error(f"Could not report time result: {e}")

    def handle_manual_time_setting(self):
        """Hold the video until the time has been entered and set (or entry is cancelled)"""
        hold = self._acquire_time_entry_hold()
        try:
            self._enter_and_set_time()
        finally:
            if hold:
                hold.close()

    def _enter_and_set_time(self):
        """Handle manual RTC time setting - step-by-step entry"""
        try:
            header = "Set RTC Time\n" + "=" * 60 + "\n\n"
            entered = ""
            values = []
            for label, low, high in (('Year', 2000, 2099), ('Month', 1, 12), ('Day', 1, 31),
                                     ('Hour', 0, 23), ('Minute', 0, 59)):
                if label == 'Day':
                    high = calendar.monthrange(values[0], values[1])[1]
                hint = "e.g., 2026" if label == 'Year' else f"{low}-{high}"

                value = self._get_numeric_input(
                    f"{header}{entered}{chr(10) if entered else ''}Enter {label} ({hint}):\n",
                    low, high, timeout=60
                )
                if value is None:
                    self.show_message("Input timeout. Cancelled.", 3)
                    return
                values.append(value)
                entered += f"{label}: {value}\n"

            year, month, day, hour, minute = values
            time_str = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00"
            show_on_console(f"{header}Setting time to: {time_str}\n\nWriting to RTC...\n")

            # The service sets the system time and writes it to the RTC
            if self._request_time_set(time_str):
                self.show_message(f"Time set successfully!\n{time_str}\nWritten to RTC.", 3)
            else:
                # Log the error for debugging
                self.logger.error(f"Failed to set time: {time_str}")
                self.show_message(f"Failed to set time: {time_str}\nCheck logs for details.", 5)

        except Exception as e:
            self.logger.error(f"Error in manual time setting: {e}")
            self.show_message(f"Error: {str(e)}", 3)
    
    def show_message(self, message, duration=3):
        """Show a message on screen for specified duration"""
        show_on_console("\n" + "=" * 60 + f"\n{message}\n" + "=" * 60 + "\n")
        time.sleep(duration)
    
    def run_demo_mode(self):
        """Run demo mode - play all folders for 1 minute each with 30 sec pause"""
        try:
            all_folders = self.get_all_valid_folders()
            
            if not all_folders:
                self.show_message("No valid video folders found for demo mode.", 5)
                return
            
            self.show_message(f"Starting demo mode with {len(all_folders)} folder(s)...", 3)
            
            self._wake_display()
            
            for folder_path, video_files in all_folders:
                folder_name = folder_path.name
                self.show_message(f"Demo: Playing {folder_name}...", 2)
                
                # Play videos for 1 minute (no looping in demo mode)
                if self.start_video(video_files, folder_path, duration=60):
                    # Wait for video playback to complete (max 65 seconds to account for startup)
                    if self.current_process:
                        try:
                            self.current_process.wait(timeout=65)
                        except subprocess.TimeoutExpired:
                            pass
                    self.stop_video(standby_hdmi=False)
                    
                    # Pause for 30 seconds between folders
                    if folder_path != all_folders[-1][0]:  # Not the last folder
                        time.sleep(30)
            
            self.show_message("Demo mode completed!", 3)
            
        except Exception as e:
            self.logger.error(f"Error in demo mode: {e}")
            self.show_message(f"Error in demo mode: {str(e)}", 5)
        finally:
            self.stop_video(standby_hdmi=True)
    
    def _wake_display(self):
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

        self._wake_display()

        if self.has_projector_config(folder_path):
            self.load_projector_config(folder_path)
            if self.projector.config.get('enable_projector', False):
                if not self.projector.connect():
                    self.logger.error("Failed to connect to projector")
                elif not self.projector.start_projector():
                    self.logger.error("Failed to start projector")
            self.handle_video_start_delay(folder_path)

        # Time entry may have started during the delays above
        if self.is_time_entry_active():
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
    
    def run(self):
        """Main loop"""
        try:
            self.usb_sync.sync_on_boot()
        except Exception as e:
            self.logger.error(f"USB sync failed: {e}")
        
        # Load the system time from the RTC
        self.time_sync.sync_time()
        
        current_folder = None
        time_entry_held = False
        while self.running:
            try:
                # Boot menu is setting the time: keep the screen free and awake for it,
                # then re-check the schedule against the new time as soon as it's done
                if self.is_time_entry_active():
                    if not time_entry_held:
                        time_entry_held = True
                        self.stop_video(standby_hdmi=False)
                        current_folder = None
                        if self.hdmi.is_available():
                            self.hdmi.wake_hdmi()
                    self._process_time_request()
                    time.sleep(0.5)
                    continue
                time_entry_held = False

                active_folder_info = self.find_active_folder()
                
                if active_folder_info:
                    folder_path, video_files = active_folder_info
                    playing = self.current_process is not None and self.current_process.poll() is None
                    if current_folder != folder_path or not playing:
                        # Folder changed, or VLC isn't running: (re)start the video
                        self.stop_video(standby_hdmi=False)
                        started = self.start_video(video_files, folder_path)
                        current_folder = folder_path if started else None
                    elif self.hdmi.is_available():
                        # Video is playing correctly. This only sends a command if
                        # the last attempt to wake the display failed.
                        self.hdmi.wake_hdmi()
                else:
                    # No active folder - stop video and put HDMI in standby
                    if self.current_folder is not None or (self.current_process is not None and self.current_process.poll() is None):
                        # Video is playing but folder is no longer active - stop it
                        self.stop_video(standby_hdmi=True)
                        current_folder = None
                    elif self.hdmi.is_available():
                        # Nothing to play. This only sends a command if the display
                        # was last told to be on, or the last attempt failed.
                        self.hdmi.standby_hdmi()

                # Wait for the next check, but react to time entry within a second
                for _ in range(CHECK_INTERVAL):
                    if self.is_time_entry_active():
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)
        
        self.stop_video(standby_hdmi=True)

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Video Looper')
    parser.add_argument('--videos-path', default=None,
                       help='Path to videos directory (default: /home/looper/videos)')
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
    parser.add_argument('--display-folder-info', action='store_true',
                       help='Display folder information on screen for 20 seconds')
    
    args = parser.parse_args()
    
    looper = VideoLooper(args.videos_path)
    
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

        for mount in usb_mounts:
            print(f"  - {mount}")
            valid_folders = looper.usb_sync.get_valid_folders(mount)
            print(f"    Valid video folders: {len(valid_folders)}")
            for folder_name in valid_folders.keys():
                print(f"      - {folder_name}")

        print(f"\nLocal video folders in {looper.videos_path}:")
        local_folders = looper.usb_sync.get_valid_folders(looper.videos_path)
        print(f"  Found {len(local_folders)} valid folder(s):")
        for folder_name in local_folders.keys():
            print(f"    - {folder_name}")

        source = looper.usb_sync.find_sync_source(usb_mounts)
        if source:
            plan = looper.usb_sync.plan_sync(source)
            print(f"\nIf synced from {source}, would:")
            for old_name, new_name in plan['rename']:
                print(f"  - Rename folder: {old_name} -> {new_name}")
            for folder_name in plan['copy']:
                print(f"  - Copy folder: {folder_name}")
            for folder_name in plan['update']:
                print(f"  - Update folder: {folder_name}")
            for folder_name in plan['delete']:
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
        return
    
    elif args.display_folder_info:
        # Display folder information on screen and show boot menu
        menu_result = looper.display_folder_info_on_screen()
        
        # Check if demo mode was selected
        if menu_result == 'demo':
            looper.run_demo_mode()
        return
    
    looper.run()

if __name__ == '__main__':
    main()
