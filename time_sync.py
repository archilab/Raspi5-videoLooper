#!/usr/bin/env python3
"""
Simplified time sync for Raspberry Pi 5:
- If internet is available at boot, write system time to RTC (hwclock -w).
- If internet is NOT available, load system time from RTC (hwclock -s / --hctosys).
"""

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import time


class TimeSyncManager:
    def __init__(self, log_file="/var/log/video_looper.log"):
        self.logger = logging.getLogger(__name__)
        self.last_sync = None
        self.running = False
        self.hwclock_cmd = self._resolve_cmd(
            "hwclock",
            "/usr/sbin/hwclock",
            "/usr/bin/hwclock",
            "/sbin/hwclock",
            "/bin/hwclock",
            "/usr/local/sbin/hwclock",
            "/bin/busybox",
        )

    def _resolve_cmd(self, name, *fallbacks):
        path = shutil.which(name)
        if path:
            return path
        for candidate in fallbacks:
            if candidate and os.path.exists(candidate):
                return candidate
        self.logger.warning(
            f"{name} not found; tried {', '.join([p for p in fallbacks if p])}. Install or adjust PATH."
        )
        return None

    def _sudo_cmd(self, cmd):
        """Run commands directly; service gains CAP_SYS_TIME via systemd."""
        return cmd

    def check_internet_connection(self, timeout=5):
        try:
            socket.create_connection(("8.8.8.8", 53), timeout)
            return True
        except OSError:
            return False

    def write_system_time_to_rtc(self):
        if not self.hwclock_cmd:
            self.logger.error("hwclock not found; cannot write system time to RTC")
            return False
        try:
            result = subprocess.run(
                self._sudo_cmd([self.hwclock_cmd, "--systohc"]),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.last_sync = "rtc_write"
                return True
            self.logger.error(f"hwclock --systohc failed: {result.stderr.strip()}")
            return False
        except Exception as e:
            self.logger.error(f"Error writing RTC: {e}")
            return False

    def load_system_time_from_rtc(self):
        if not self.hwclock_cmd:
            self.logger.error("hwclock not found; cannot read RTC")
            return False
        try:
            result = subprocess.run(
                self._sudo_cmd([self.hwclock_cmd, "--hctosys"]),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.last_sync = "rtc_read"
                return True
            self.logger.error(f"hwclock --hctosys failed: {result.stderr.strip()}")
            return False
        except Exception as e:
            self.logger.error(f"Error reading RTC: {e}")
            return False

    def sync_time(self):
        has_net = self.check_internet_connection()
        if has_net:
            # Internet available: trust system time (set by systemd-timesyncd) and store into RTC
            if self.write_system_time_to_rtc():
                self.logger.info("RTC updated from system time (internet available).")
                return True
            self.logger.warning("Failed to update RTC from system time.")
            return False
        else:
            # No internet: load time from RTC into system
            if self.load_system_time_from_rtc():
                self.logger.info("System time loaded from RTC (no internet).")
                return True
            self.logger.warning("Failed to load system time from RTC.")
            return False

    # Compatibility helpers to keep video_looper intact -----------------
    def sync_rtc_with_ntp(self):
        """Assumes systemd-timesyncd sets system time when net is up; then writes RTC."""
        if not self.check_internet_connection():
            return False
        return self.write_system_time_to_rtc()

    def set_time_manually(self, time_str):
        """Fallback manual set using date -s, then write to RTC."""
        try:
            result = subprocess.run(
                self._sudo_cmd(["date", "-s", time_str]),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                self.logger.error(f"date -s failed: {result.stderr.strip()}")
                return False
            return self.write_system_time_to_rtc()
        except Exception as e:
            self.logger.error(f"Manual time set failed: {e}")
            return False

    def start_background_sync(self):
        """No-op in simplified mode."""
        self.running = False

    def stop_background_sync(self):
        """No-op in simplified mode."""
        self.running = False

    def get_time_status(self):
        return {
            "internet_available": self.check_internet_connection(),
            "rtc_available": self.hwclock_cmd is not None,
            "last_sync": self.last_sync,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Simplified Time Sync for Raspberry Pi 5 Video Looper"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Perform one-time sync: net -> RTC (write) else RTC -> system (read)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="/var/log/video_looper.log",
        help="Path to log file",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(args.log_file), logging.StreamHandler(sys.stdout)],
    )

    manager = TimeSyncManager(args.log_file)

    if args.sync:
        ok = manager.sync_time()
        sys.exit(0 if ok else 1)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()

