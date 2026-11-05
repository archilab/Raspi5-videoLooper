#!/usr/bin/env python3
"""
RTC-only time sync for Raspberry Pi 5:
- Loads system time from the RTC at startup.
- The RTC is kept in UTC, and NTP is off unless switched on from the boot menu.
- With NTP on, the system clock follows it when there's internet, and the RTC follows
  the system clock, so the time survives a power cut without internet.
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
NTP_SYNCED_FILE = "/run/systemd/timesync/synchronized"  # Exists once NTP has set the clock


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

    def _timedatectl(self, *args):
        """Run timedatectl, returning the finished process, or None if it couldn't be run"""
        try:
            return subprocess.run(["timedatectl", *args], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.error(f"timedatectl could not run: {e}")
            return None

    def ntp_enabled(self):
        """Check whether the time source is NTP rather than the RTC alone"""
        result = self._timedatectl("show", "-p", "NTP", "--value")
        return result is not None and result.stdout.strip() == "yes"

    def set_ntp(self, enabled):
        """Switch NTP on or off, returning True if that worked"""
        result = self._timedatectl("set-ntp", "true" if enabled else "false")
        if result is None or result.returncode != 0:
            self.logger.error(f"Could not switch NTP: {result.stderr.strip() if result else 'timedatectl failed'}")
            return False
        return True

    def is_ntp_synced(self):
        """Check whether NTP is on and has set the clock"""
        # The file first: this runs early in boot, before timedatectl can answer
        return os.path.exists(NTP_SYNCED_FILE) and self.ntp_enabled()

    def update_rtc_from_ntp(self):
        """Copy NTP's time to the RTC, if NTP has set the clock"""
        if self.is_ntp_synced():
            self.write_system_time_to_rtc()

    def sync_time(self):
        """Load system time from the RTC, unless NTP has already set a better time"""
        if self.is_ntp_synced():
            return True
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
            "mode": "NTP when internet is available" if self.ntp_enabled() else "RTC only",
            "ntp_synced": self.is_ntp_synced(),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Simplified Time Sync for Raspberry Pi 5 Video Looper"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Load system time from RTC, unless NTP has already set it",
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
