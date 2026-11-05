#!/usr/bin/env python3
"""
Coordinates the boot menu and the looper service while the time is being set.

They run as separate processes. The menu takes a file lock to hold the video, which
the kernel releases even if the menu crashes. The menu has no permission to change
the clock, so it passes the entered time to the service through small files in RAM.
"""

import fcntl
import logging
import os
import time
from constants import (
    TIME_ENTRY_LOCK_FILE, TIME_SET_REQUEST_FILE, TIME_SET_RESULT_FILE, TIME_SET_TIMEOUT
)

logger = logging.getLogger(__name__)


def acquire_hold():
    """
    Menu side: tell the service to hold the video while the time is being entered.
    Returns the open lock file (close it to release), or None if it can't be taken.
    """
    try:
        lock_file = open(TIME_ENTRY_LOCK_FILE, 'a')
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return lock_file
    except OSError as e:
        logger.error(f"Could not hold video during time entry: {e}")
        return None


def is_active():
    """Check whether the boot menu currently holds the time entry lock"""
    try:
        with open(TIME_ENTRY_LOCK_FILE, 'a') as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def _write_file_atomic(path, text):
    """Write a small file so a reader never sees it half-written"""
    temp_path = f"{path}.tmp"
    with open(temp_path, 'w') as f:
        f.write(text)
    os.replace(temp_path, path)


def _remove_file(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def request_time_set(time_str):
    """
    Menu side: ask the service to set the clock, since only it has permission.
    Returns True once the service confirms the system clock and RTC are both set.
    """
    _remove_file(TIME_SET_RESULT_FILE)
    try:
        _write_file_atomic(TIME_SET_REQUEST_FILE, time_str)
    except OSError as e:
        logger.error(f"Could not send time request: {e}")
        return False

    deadline = time.monotonic() + TIME_SET_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with open(TIME_SET_RESULT_FILE) as f:
                result = f.read().strip()
            _remove_file(TIME_SET_RESULT_FILE)
            return result == 'ok'
        except OSError:
            time.sleep(0.2)

    # Service isn't answering: don't leave a request that could apply later
    _remove_file(TIME_SET_REQUEST_FILE)
    logger.error("Video looper service did not answer the time request")
    return False


def process_request(set_time):
    """Service side: if the menu has asked, call set_time(time_str) and report the result"""
    try:
        # /dev/shm is writable by every user, so only accept our own user's requests
        if os.stat(TIME_SET_REQUEST_FILE).st_uid != os.getuid():
            return
        with open(TIME_SET_REQUEST_FILE) as f:
            time_str = f.read().strip()
    except OSError:
        return
    _remove_file(TIME_SET_REQUEST_FILE)

    success = set_time(time_str)
    try:
        _write_file_atomic(TIME_SET_RESULT_FILE, 'ok' if success else 'failed')
    except OSError as e:
        logger.error(f"Could not report time result: {e}")
