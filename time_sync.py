#!/usr/bin/env python3
"""
RTC-only time sync for Raspberry Pi 5:
- Loads system time from the RTC at startup.
- NTP is disabled; the system relies entirely on the RTC, which is kept in UTC.
- Changing the clock needs CAP_SYS_TIME, which the systemd services grant.
"""

import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

RTC_EPOCH_FILE = "/sys/class/rtc/rtc0/since_epoch"


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class TimeSyncManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.last_sync = None
        self.hwclock_cmd = shutil.which("hwclock")
        if not self.hwclock_cmd and os.path.exists("/usr/sbin/hwclock"):
            self.hwclock_cmd = "/usr/sbin/hwclock"
        if not self.hwclock_cmd:
            self.logger.error("hwclock not found")

    def _run_hwclock(self, operation):
        """Run hwclock, returning an error message or None on success"""
        if not self.hwclock_cmd:
            return "hwclock not found"
        try:
            # --noadjfile: /etc/adjtime is root-only, and the RTC is kept in UTC
            result = subprocess.run(
                [self.hwclock_cmd, operation, "--noadjfile", "--utc"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return str(e)
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip() or "unknown error"
        return None

    def _set_system_time(self, timestamp):
        """Set the system clock, returning an error message or None on success"""
        libc = ctypes.CDLL(None, use_errno=True)
        seconds = int(timestamp)
        tv = _Timeval(seconds, int((timestamp - seconds) * 1_000_000))
        if libc.settimeofday(ctypes.byref(tv), None) != 0:
            return os.strerror(ctypes.get_errno())
        return None

    def write_system_time_to_rtc(self):
        error = self._run_hwclock("--systohc")
        if error:
            self.logger.error(f"Could not write system time to RTC: {error}")
            return False
        self.last_sync = "rtc_write"
        return True

    def _load_from_rtc_file(self):
        """
        Set the system clock from sysfs, which is readable without device access.
        Needed when this runs early in boot, before udev has set the RTC's permissions.
        Returns an error message or None on success.
        """
        try:
            with open(RTC_EPOCH_FILE) as f:
                return self._set_system_time(int(f.read().strip()))
        except (OSError, ValueError) as e:
            return str(e)

    def load_system_time_from_rtc(self, retries=3, delay=2):
        """Load system time from the RTC, retrying in case it isn't ready yet"""
        for attempt in range(retries):
            if attempt:
                time.sleep(delay)
            hwclock_error = self._run_hwclock("--hctosys")
            file_error = hwclock_error and self._load_from_rtc_file()
            if not hwclock_error or not file_error:
                self.last_sync = "rtc_read"
                return True
        self.logger.error(
            f"Could not load system time from RTC: {hwclock_error}; from {RTC_EPOCH_FILE}: {file_error}"
        )
        return False

    def sync_time(self):
        """Load system time from the RTC (NTP is disabled)"""
        return self.load_system_time_from_rtc()

    def set_time_manually(self, time_str):
        """Set the system clock and RTC to a local time formatted YYYY-MM-DD HH:MM:SS"""
        try:
            timestamp = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S').timestamp()
        except ValueError:
            self.logger.error(f"Invalid time format: {time_str}")
            return False

        error = self._set_system_time(timestamp)
        if error:
            self.logger.error(f"Could not set system time to {time_str}: {error}")
            return False
        # Without the RTC the new time would be lost on the next boot
        return self.write_system_time_to_rtc()

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
