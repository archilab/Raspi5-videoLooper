#!/usr/bin/env python3
"""The boot menu shown on the HDMI console after login: folder list, demo mode, time and Wi-Fi settings"""

import calendar
import codecs
import logging
import os
import select
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime
import network_setup
import nextcloud_sync
import scheduler
import time_entry
from console import show_on_console


# Keep waiting this long since the last key press on the text and list screens
ENTRY_TIMEOUT = 120  # seconds


class BootMenu:
    def __init__(self, videos_path, player, time_sync):
        self.logger = logging.getLogger(__name__)
        self.videos_path = videos_path
        self.player = player
        self.time_sync = time_sync
        self.wifi_status = None
        self.time_status = None
        self.nextcloud_status = None

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
                    
                    if scheduler.is_always_folder(folder_name):
                        lines.append("     Schedule: Plays all the time")
                    elif schedule:
                        start_date = schedule['start_date'].strftime('%Y-%m-%d')
                        end_date = schedule['end_date'].strftime('%Y-%m-%d')
                        windows = " and ".join(
                            f"{start.strftime('%H:%M')} to {end.strftime('%H:%M')}"
                            for start, end in schedule['windows']
                        )
                        lines.append(f"     Schedule: {start_date} to {end_date}, {windows}")
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
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while True:
                data = os.read(sys.stdin.fileno(), 1)
                if not data:
                    return ''
                text = decoder.decode(data)  # Empty until a multi-byte character is complete
                if text:
                    return text
        except (OSError, ValueError):
            return None
    
    def display_boot_menu(self):
        """Display boot menu UI and handle user selection - stable version"""
        try:
            menu_timeout = 20  # seconds to wait for input
            self.wifi_status = network_setup.current_wifi() or "not connected"
            self.time_status = "NTP" if self.time_sync.ntp_enabled() else "RTC only"
            self.nextcloud_status = nextcloud_sync.status_line()
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
                        elif char == '3':
                            self._show_feedback("Option 3: Setting Wi-Fi...")
                            time.sleep(0.5)
                            self._with_hold(self._set_wifi)
                            return None
                        elif char == '4':
                            self._show_feedback("Option 4: Time source...")
                            time.sleep(0.5)
                            self._with_hold(self._set_time_source)
                            return None
                        elif char == '5':
                            self._show_feedback("Option 5: Nextcloud...")
                            time.sleep(0.5)
                            self._with_hold(self._set_nextcloud)
                            return None
                        elif char == '\n' or char == '\r':
                            return None  # Enter pressed, continue
                        else:
                            # Invalid key - show error and restart
                            self._show_feedback(f"Invalid option: {char}. Press 1 to 5, or Enter...")
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
            "  3. Set Wi-Fi" + (f" (now: {self.wifi_status})" if self.wifi_status else ""),
            "  4. Time source" + (f" (now: {self.time_status})" if self.time_status else ""),
            "  5. Nextcloud" + (f" (now: {self.nextcloud_status})" if self.nextcloud_status else ""),
            "",
            "  Press 1 to 5, or Enter to continue...",
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
        self._with_hold(self._enter_and_set_time)

    def _with_hold(self, action):
        """Run a menu screen with the service's video stopped and the display kept on"""
        hold = time_entry.acquire_hold()
        try:
            action()
        finally:
            if hold:
                hold.close()

    def _get_key(self, valid_keys, timeout=ENTRY_TIMEOUT):
        """Wait for one of these keys, returning it, or None for Enter, Ctrl+C or a timeout"""
        self._setup_terminal_input()
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                char = self.get_char_blocking(timeout=0.5)
                if char in ('\n', '\r', '\x03'):
                    return None
                if char and char in valid_keys:
                    return char
            return None
        finally:
            self._restore_terminal_input()

    def _get_text_input(self, prompt, secret=False, timeout=ENTRY_TIMEOUT):
        """
        Read a line of text, returning it, or None if cancelled with Esc or Ctrl+C or
        after no key for the timeout. If secret, it shows as stars until Tab is pressed.
        """
        text = ""
        reveal = False
        self._setup_terminal_input()

        def show():
            shown = text if reveal or not secret else "*" * len(text)
            hint = "\n\n  Tab shows or hides it. " if secret else "\n\n  "
            show_on_console(f"{prompt}\n  > {shown}{hint}Enter to confirm, Esc to cancel.\n")

        try:
            show()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                char = self.get_char_blocking(timeout=0.5)
                if not char:
                    continue
                deadline = time.monotonic() + timeout
                if char in ('\n', '\r'):
                    return text
                if char == '\x03':
                    return None
                if char == '\x1b':
                    # Esc alone cancels, but arrow and function keys send Esc plus more
                    following = self.get_char_blocking(timeout=0.05)
                    if not following:
                        return None
                    while following and not (following.isalpha() or following == '~'):
                        following = self.get_char_blocking(timeout=0.05)
                    continue
                if char == '\t':
                    reveal = not reveal
                elif char in ('\x7f', '\b'):
                    text = text[:-1]
                elif char.isprintable() and char != '\ufffd':
                    text += char
                show()
            return None
        finally:
            self._restore_terminal_input()

    def _ask_wifi_password(self, ssid, optional=False):
        """Ask for a valid Wi-Fi password, returning it, or None if cancelled"""
        prompt = f"{self.WIFI_HEADER}Password for {ssid}" + (" (leave empty if none):" if optional else ":")
        problem = ""
        while True:
            password = self._get_text_input(problem + prompt, secret=True)
            if password is None or (optional and password == ""):
                return password
            if not 8 <= len(password.encode()) <= 63:
                problem = "A Wi-Fi password has 8 to 63 characters.\n\n"
            elif password != password.strip():
                # NetworkManager's editor would silently remove these
                problem = "A password that starts or ends with a space can't be set here.\n\n"
            else:
                return password

    WIFI_HEADER = "Set Wi-Fi\n" + "=" * 60 + "\n\n"

    def _choose_wifi_network(self):
        """Show visible networks, returning the chosen one's details, or None if cancelled"""
        show_on_console(f"{self.WIFI_HEADER}Scanning for networks...\n")
        networks = network_setup.scan()[:9]
        lines = [f"  {number}. {network['ssid']} ({network['signal']}%, {network['security'].strip() or 'open'})"
                 for number, network in enumerate(networks, 1)]
        if not lines:
            lines = ["  No networks found."]
        show_on_console(f"{self.WIFI_HEADER}Choose a network:\n\n" + "\n".join(lines) +
                        "\n\n  0. Type the name of a hidden network\n\n  Enter to cancel.\n")

        key = self._get_key('0' + ''.join(str(n) for n in range(1, len(networks) + 1)))
        if key is None:
            return None
        if key != '0':
            return networks[int(key) - 1]

        ssid = self._get_text_input(f"{self.WIFI_HEADER}Name of the hidden network:")
        if not ssid or len(ssid.encode()) > 32:
            return None
        return {'ssid': ssid, 'security': '', 'hidden': True}

    def _set_wifi(self):
        """Choose a Wi-Fi network, enter its password and connect"""
        try:
            network = self._choose_wifi_network()
            if network is None:
                self.show_message("Wi-Fi not changed.", 2)
                return

            ssid = network['ssid']
            hidden = network.get('hidden', False)
            key_mgmt = 'wpa-psk' if hidden else network_setup.key_management(network['security'])
            if key_mgmt == 'unsupported':
                self.show_message(f"{ssid} uses {network['security']}, which can't be set up here.\nWi-Fi not changed.", 5)
                return

            password = None
            if key_mgmt:
                password = self._ask_wifi_password(ssid, optional=hidden)
                if password is None:
                    self.show_message("Wi-Fi not changed.", 2)
                    return
                if not password:  # A hidden network with no password
                    key_mgmt = None

            show_on_console(f"{self.WIFI_HEADER}Connecting to {ssid}...\nThis can take up to a minute.\n")
            _, message = network_setup.connect(ssid, password, key_mgmt, hidden)
            self.show_message(message, 5)
        except Exception as e:
            # Not the exception's text, in case it ever includes the password
            self.logger.error(f"Error in Wi-Fi setup: {type(e).__name__}")
            self.show_message("Wi-Fi setup failed. Wi-Fi may not have changed.", 5)

    NEXTCLOUD_HEADER = "Nextcloud\n" + "=" * 60 + "\n\n"

    def _set_nextcloud(self):
        """Show Nextcloud's status, and offer to set it up, switch it or sync now"""
        try:
            config = nextcloud_sync.load_config()
            status = nextcloud_sync.read_status()
            lines = [f"Now: {nextcloud_sync.status_line()}"]
            if status:
                lines.append(f"Last check at {status['time']}: {status['message']}")
            lines += ["", "  1. Set up with a share link", "  2. Set up with an account and app password"]
            if config:
                lines.append("  3. Turn off" if config['enabled'] else "  3. Turn on")
                if config['enabled']:
                    lines.append("  4. Sync now")
            lines += ["", "  Enter to leave it."]
            show_on_console(self.NEXTCLOUD_HEADER + "\n".join(lines) + "\n")

            valid = '12' + ('' if not config else '34' if config['enabled'] else '3')
            key = self._get_key(valid)
            if key == '1':
                self._set_up_nextcloud_share()
            elif key == '2':
                self._set_up_nextcloud_account()
            elif key == '3' and config['enabled']:
                config['enabled'] = False
                nextcloud_sync.save_config(config)
                self.show_message("Nextcloud is off.\nUSB video sync works again the next time the service starts.", 5)
            elif key == '3':
                self._turn_on_nextcloud(config)
            elif key == '4':
                nextcloud_sync.request_sync()
                self.show_message("Nextcloud will check now, and the video returns meanwhile.", 3)
        except Exception as e:
            # Not the exception's text, in case it ever includes a password or share link
            self.logger.error(f"Error in Nextcloud setup: {type(e).__name__}")
            self.show_message("Nextcloud setup failed. Nothing was changed.", 5)

    def _set_up_nextcloud_share(self):
        share_url = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Share link, like https://cloud.example.com/s/abc123:")
        if not share_url:
            return
        password = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Share password (leave empty if none):", secret=True)
        if password is not None:
            self._finish_nextcloud_setup({'share_url': share_url, 'password': password})

    def _set_up_nextcloud_account(self):
        server = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Server, like https://cloud.example.com:")
        if not server:
            return
        username = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Username:")
        if not username:
            return
        folder = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Folder holding the video folders, like Videos/Looper\n"
                                      "(leave empty for the top level):")
        if folder is None:
            return
        password = self._get_text_input(f"{self.NEXTCLOUD_HEADER}App password, created in Nextcloud's security settings:",
                                        secret=True)
        if password:
            self._finish_nextcloud_setup({'server': server, 'username': username, 'folder': folder, 'password': password})

    def _finish_nextcloud_setup(self, fields):
        interval = self._get_text_input(f"{self.NEXTCLOUD_HEADER}Check every how many minutes? "
                                        f"(leave empty for {nextcloud_sync.NEXTCLOUD_DEFAULT_INTERVAL}):")
        if interval is None:
            return
        fields['interval'] = interval
        try:
            config = nextcloud_sync.make_config(fields)
        except ValueError as e:
            self.show_message(f"{e}\nNothing was changed.", 5)
            return
        self._turn_on_nextcloud(config)

    def _turn_on_nextcloud(self, config):
        """Test the connection and show what would happen, then turn on if confirmed"""
        show_on_console(f"{self.NEXTCLOUD_HEADER}Connecting...\n")
        try:
            remote, plan = nextcloud_sync.preview(config, self.videos_path)
        except nextcloud_sync.NextcloudError as e:
            self.show_message(f"{e}\nNothing was changed.", 6)
            return

        lines = [f"Connected, and found {len(remote)} valid folder(s).", ""]
        if remote:
            lines.append(f"Turning this on will download {len(plan['copy'])} folder(s), rename {len(plan['rename'])}, "
                         f"and REMOVE {len(plan['delete'])} local folder(s)")
            lines += [f"    {name}" for name in plan['delete']]
            lines.append("that aren't on Nextcloud.")
        else:
            lines.append("With no valid folders on Nextcloud, nothing changes for now.")
        lines += ["USB video sync will be off.", "", "  1. Turn on", "", "  Enter to cancel."]
        show_on_console(self.NEXTCLOUD_HEADER + "\n".join(lines) + "\n")

        if self._get_key('1') is None:
            self.show_message("Nothing was changed.", 2)
            return
        config['enabled'] = True
        nextcloud_sync.save_config(config)
        nextcloud_sync.request_sync()
        self.show_message("Nextcloud is on, and will check now.", 3)

    def _set_time_source(self):
        """Show the time source, and offer to switch it"""
        try:
            ntp = self.time_sync.ntp_enabled()
            now = "NTP when internet is available" if ntp else "RTC only"
            other = "RTC only" if ntp else "NTP when internet is available"
            show_on_console(f"Time source\n{'=' * 60}\n\nNow: {now}\n\n  1. Switch to {other}\n\n  Enter to leave it.\n")
            if self._get_key('1') is None:
                return

            if not self.time_sync.set_ntp(not ntp):
                self.show_message("Could not switch the time source.", 5)
            elif ntp:
                self.show_message("Time source: RTC only.\nSet the time from this menu if it needs correcting.", 5)
            else:
                self.show_message("Time source: NTP when internet is available.\nThe clock updates once the Pi reaches the internet.", 5)
        except Exception as e:
            self.logger.error(f"Error setting the time source: {e}")
            self.show_message(f"Error: {str(e)}", 3)
    
    def _enter_and_set_time(self):
        """Handle manual RTC time setting - step-by-step entry"""
        try:
            if self.time_sync.ntp_enabled():
                self.show_message("NTP is on, so it would overwrite a time set here.\n"
                                  "Switch the time source to RTC only first, with option 4.", 5)
                return

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
        """Play all folders for 1 minute each with a 30 second pause, while the service waits"""
        hold = time_entry.acquire_hold()
        try:
            self._play_demo()
        finally:
            # The service takes the display back when the hold ends. It doesn't know this
            # process started the projector, so switch it off here if nothing is scheduled
            self.player.stop_video(standby_hdmi=False)
            if scheduler.find_active_folder(self.videos_path):
                self.player.release_projector()
            else:
                self.player.stop_projector()
            if hold:
                hold.close()

    def _play_demo(self):
        try:
            all_folders = scheduler.get_all_valid_folders(self.videos_path)

            if not all_folders:
                self.show_message("No valid video folders found for demo mode.", 5)
                return

            self.show_message(f"Starting demo mode with {len(all_folders)} folder(s)...", 3)

            # Only one VLC can use the display, so the service's has to go first
            self.player.wait_for_vlc_to_exit()
            self.player.wake_display()

            for folder_path, video_files in all_folders:
                folder_name = folder_path.name
                self.show_message(f"Demo: Playing {folder_name}...", 2)

                # Play videos for 1 minute (no looping in demo mode)
                if self.player.start_video(video_files, folder_path, duration=60, ignore_hold=True):
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
