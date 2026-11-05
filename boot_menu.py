#!/usr/bin/env python3
"""The boot menu shown on the HDMI console after login: folder list, demo mode and setting the time"""

import calendar
import logging
import os
import select
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime
import scheduler
import time_entry
from console import show_on_console


class BootMenu:
    def __init__(self, videos_path, player):
        self.logger = logging.getLogger(__name__)
        self.videos_path = videos_path
        self.player = player

    def display_folder_info_on_screen(self):
        """Display folder information on HDMI screen"""
        try:
            # Get all valid folders
            all_folders = scheduler.get_all_valid_folders(self.videos_path)
            
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
                    schedule = scheduler.parse_folder_name(folder_name)
                    
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
            # Read the terminal directly: text-mode stdin would hold back an Enter ("\r")
            # until the next key arrives, in case it's the start of "\r\n"
            return os.read(sys.stdin.fileno(), 1).decode(errors='ignore')
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
    
    def handle_manual_time_setting(self):
        """Hold the video until the time has been entered and set (or entry is cancelled)"""
        hold = time_entry.acquire_hold()
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
            if time_entry.request_time_set(time_str):
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
            all_folders = scheduler.get_all_valid_folders(self.videos_path)
            
            if not all_folders:
                self.show_message("No valid video folders found for demo mode.", 5)
                return
            
            self.show_message(f"Starting demo mode with {len(all_folders)} folder(s)...", 3)
            
            self.player.wake_display()
            
            for folder_path, video_files in all_folders:
                folder_name = folder_path.name
                self.show_message(f"Demo: Playing {folder_name}...", 2)
                
                # Play videos for 1 minute (no looping in demo mode)
                if self.player.start_video(video_files, folder_path, duration=60):
                    # Wait for video playback to complete (max 65 seconds to account for startup)
                    if self.player.current_process:
                        try:
                            self.player.current_process.wait(timeout=65)
                        except subprocess.TimeoutExpired:
                            pass
                    self.player.stop_video(standby_hdmi=False)
                    
                    # Pause for 30 seconds between folders
                    if folder_path != all_folders[-1][0]:  # Not the last folder
                        time.sleep(30)
            
            self.show_message("Demo mode completed!", 3)
            
        except Exception as e:
            self.logger.error(f"Error in demo mode: {e}")
            self.show_message(f"Error in demo mode: {str(e)}", 5)
        finally:
            self.player.stop_video(standby_hdmi=True)
