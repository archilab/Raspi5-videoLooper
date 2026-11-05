#!/usr/bin/env python3
"""
RTC-only time sync for Raspberry Pi 5:
- Always loads system time from RTC on boot (hwclock --hctosys).
- NTP is disabled; system relies entirely on RTC.
"""

import argparse
import ctypes
import ctypes.util
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime


class TimeSyncManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.last_sync = None
        self.hwclock_cmd = self._resolve_cmd(
            "hwclock",
            "/usr/sbin/hwclock",
            "/usr/bin/hwclock",
            "/sbin/hwclock",
            "/bin/hwclock",
            "/usr/local/sbin/hwclock",
            "/bin/busybox",
        )
        # Check if hwclock has required capabilities
        if self.hwclock_cmd and os.path.exists(self.hwclock_cmd):
            try:
                result = subprocess.run(
                    ["getcap", self.hwclock_cmd],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "cap_sys_time" not in result.stdout:
                    self.logger.error(
                        f"hwclock missing CAP_SYS_TIME capability. "
                        f"Run: sudo setcap cap_sys_time+ep {self.hwclock_cmd}"
                    )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # getcap not available or timeout - assume it's set up correctly
                pass

    def _resolve_cmd(self, name, *fallbacks):
        path = shutil.which(name)
        if path:
            return path
        for candidate in fallbacks:
            if candidate and os.path.exists(candidate):
                return candidate
        # Only log if critical command missing
        if name == "hwclock":
            self.logger.error(f"hwclock not found; tried {', '.join([p for p in fallbacks if p])}")
        return None

    def write_system_time_to_rtc(self):
        if not self.hwclock_cmd:
            self.logger.error("hwclock not found; cannot write system time to RTC")
            return False
        try:
            result = subprocess.run(
                # --noadjfile: /etc/adjtime is root-only, and the RTC is kept in UTC
                [self.hwclock_cmd, "--systohc", "--noadjfile", "--utc"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.last_sync = "rtc_write"
                return True
            error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
            if "permission" in error_msg.lower() or "operation not permitted" in error_msg.lower():
                self.logger.error(
                    f"hwclock --systohc failed: {error_msg}. "
                    f"Ensure hwclock has CAP_SYS_TIME: sudo setcap cap_sys_time+ep {self.hwclock_cmd}"
                )
            else:
                self.logger.error(f"hwclock --systohc failed: {error_msg}")
            return False
        except Exception as e:
            self.logger.error(f"Error writing RTC: {e}")
            return False

    def _check_rtc_device(self):
        """Check if RTC device is available."""
        rtc_devices = ["/dev/rtc0", "/dev/rtc", "/dev/misc/rtc0"]
        for device in rtc_devices:
            if os.path.exists(device):
                return device
        # Also check /sys/class/rtc
        if os.path.exists("/sys/class/rtc"):
            try:
                for rtc_dir in os.listdir("/sys/class/rtc"):
                    rtc_path = f"/dev/{rtc_dir}"
                    if os.path.exists(rtc_path):
                        return rtc_path
            except OSError:
                pass
        return None

    def load_system_time_from_rtc(self, retries=3, delay=2):
        """Load system time from RTC with retries."""
        if not self.hwclock_cmd:
            self.logger.error("hwclock not found; cannot read RTC")
            return False
        
        # Check if RTC device exists
        rtc_device = self._check_rtc_device()
        if not rtc_device:
            # Try to find RTC device via /sys/class/rtc
            try:
                if os.path.exists("/sys/class/rtc"):
                    for rtc_dir in os.listdir("/sys/class/rtc"):
                        dev_path = f"/dev/{rtc_dir}"
                        if os.path.exists(dev_path):
                            rtc_device = dev_path
                            break
            except OSError:
                pass
        
        # Build list of commands to try
        commands_to_try = []
        if rtc_device:
            # Try with explicit device first
            commands_to_try.append([self.hwclock_cmd, f"--rtc={rtc_device}", "--hctosys"])
            commands_to_try.append([self.hwclock_cmd, "--rtc", rtc_device, "--hctosys"])
        
        # Try default (no device specified)
        commands_to_try.append([self.hwclock_cmd, "--hctosys"])
        commands_to_try.append([self.hwclock_cmd, "-s"])  # Alternative syntax
        
        # Try with verbose to get more info
        if rtc_device:
            commands_to_try.append([self.hwclock_cmd, "--verbose", f"--rtc={rtc_device}", "--hctosys"])
        
        last_error = None
        for attempt in range(1, retries + 1):
            for cmd in commands_to_try:
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        self.last_sync = "rtc_read"
                        return True
                except Exception:
                    continue
            
            # If we get here, all commands failed for this attempt
            if attempt < retries:
                time.sleep(delay)
        
        # Try alternative: read time directly from /sys/class/rtc
        try:
            if os.path.exists("/sys/class/rtc"):
                for rtc_dir in os.listdir("/sys/class/rtc"):
                    rtc_sys_path = f"/sys/class/rtc/{rtc_dir}"
                    since_epoch_file = f"{rtc_sys_path}/since_epoch"
                    if os.path.exists(since_epoch_file):
                        try:
                            with open(since_epoch_file, 'r') as f:
                                rtc_epoch = int(f.read().strip())
                            # Set system time using date command
                            date_cmd = f"date -s '@{rtc_epoch}'"
                            result = subprocess.run(
                                ["sh", "-c", date_cmd],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            if result.returncode == 0:
                                self.last_sync = "rtc_read"
                                return True
                        except (ValueError, OSError, IOError):
                            continue
        except OSError:
            pass
        
        # Try alternative: use timedatectl if available
        try:
            result = subprocess.run(
                ["timedatectl", "set-local-rtc", "1"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Now try to read from RTC using hwclock again
                result = subprocess.run(
                    [self.hwclock_cmd, "--hctosys"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    self.last_sync = "rtc_read"
                    return True
        except Exception:
            pass
        
        # Final error message
        if last_error:
            self.logger.error(f"hwclock --hctosys failed after {retries} attempts with all methods: {last_error}")
        else:
            self.logger.error(f"hwclock --hctosys failed after {retries} attempts: Cannot access RTC via any known method")
        return False

    def sync_time(self):
        """Always load system time from RTC (NTP disabled)."""
        if self.load_system_time_from_rtc():
            return True
        self.logger.error("Failed to load system time from RTC.")
        return False

    def _set_system_time_direct(self, dt):
        """Set system time directly using settimeofday (requires CAP_SYS_TIME)"""
        try:
            # Parse datetime if string
            if isinstance(dt, str):
                try:
                    dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        dt = datetime.strptime(dt, '%Y-%m-%d %H:%M')
                    except ValueError:
                        self.logger.error(f"Invalid time format: {dt}")
                        return False
            
            # Convert to timestamp (UTC)
            timestamp = dt.timestamp()
            
            # Use ctypes to call settimeofday
            libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
            
            # Define timeval structure
            class timeval(ctypes.Structure):
                _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]
            
            # Create timeval
            tv = timeval()
            tv.tv_sec = int(timestamp)
            tv.tv_usec = int((timestamp - tv.tv_sec) * 1000000)
            
            # Call settimeofday
            # settimeofday(tv, tz) - tz can be None
            result = libc.settimeofday(ctypes.byref(tv), None)
            if result == 0:
                return True
            return False
        except Exception:
            return False
    
    def set_time_manually(self, time_str):
        """Set system time manually by writing to RTC first, then reading back."""
        try:
            # Parse time string
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    self.logger.error(f"Invalid time format: {time_str}")
                    return False
            
            if not self.hwclock_cmd:
                self.logger.error("hwclock not found")
                return False
            
            # Method 1: Try direct system call first (if capability is available)
            if self._set_system_time_direct(dt):
                # Without the RTC the new time would be lost on the next boot
                return self.write_system_time_to_rtc()
            
            # Method 2: Try to write to RTC via /sys/class/rtc (since we can read from it)
            rtc_written = False
            try:
                if os.path.exists("/sys/class/rtc"):
                    for rtc_dir in os.listdir("/sys/class/rtc"):
                        rtc_sys_path = f"/sys/class/rtc/{rtc_dir}"
                        since_epoch_file = f"{rtc_sys_path}/since_epoch"
                        if os.path.exists(since_epoch_file):
                            try:
                                timestamp = int(dt.timestamp())
                                with open(since_epoch_file, 'w') as f:
                                    f.write(str(timestamp))
                                rtc_written = True
                                break
                            except (OSError, IOError, PermissionError):
                                continue
            except OSError:
                pass
            
            if rtc_written:
                if self.load_system_time_from_rtc():
                    return True
                self.logger.error("RTC time written but failed to load to system")
                return False
            
            # Method 3: Try hwclock --set with explicit RTC device
            hwclock_result = None
            rtc_device = self._check_rtc_device()
            
            if rtc_device:
                # Try with explicit device
                hwclock_result = subprocess.run(
                    [self.hwclock_cmd, f"--rtc={rtc_device}", "--set", f"--date={time_str}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            
            if not hwclock_result or hwclock_result.returncode != 0:
                # Try without explicit device
                hwclock_result = subprocess.run(
                    [self.hwclock_cmd, "--set", f"--date={time_str}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            
            if hwclock_result and hwclock_result.returncode == 0:
                if self.load_system_time_from_rtc():
                    return True
                self.logger.error("RTC time set but failed to load to system")
                return False
            
            # All methods failed
            self.logger.error(f"Failed to set time: {time_str}")
            return False
            
        except Exception as e:
            self.logger.error(f"Time set failed: {e}")
            return False

    def get_time_status(self):
        return {
            "rtc_available": self.hwclock_cmd is not None,
            "last_sync": self.last_sync,
            "mode": "RTC-only (NTP disabled)",
        }


def main():
    parser = argparse.ArgumentParser(
        description="Simplified Time Sync for Raspberry Pi 5 Video Looper"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Load system time from RTC (RTC-only mode, NTP disabled)",
    )
    args = parser.parse_args()

    # Minimal logging - WARNING and ERROR only, no file writes to reduce SD card wear
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],  # Only stderr, no file
    )

    manager = TimeSyncManager()

    if args.sync:
        ok = manager.sync_time()
        sys.exit(0 if ok else 1)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()

