#!/usr/bin/env python3
"""
Decides what should play, from folder names in the videos directory
Format: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM, with more windows joined by _and_
Examples: 2024-01-01_to_2024-01-31_0900_to_1800
          2024-01-01_to_2024-01-31_0500_to_0900_and_1600_to_2300

If a window's end time is before its start time it runs overnight. It starts on each
date in the range, so the last night continues into the morning after the end date:
2024-01-01_to_2024-01-03_2200_to_0600 plays from 22:00 on Jan 1 until 06:00 on Jan 4.

A local folder called "always" plays all the time, unless a schedule is active. The USB
sync creates it from videos at the top level of a drive that has no schedule folders.
"""

import logging
import re
from datetime import date, datetime, timedelta
from constants import ALWAYS_FOLDER, FOLDER_NAME_PATTERN, DATE_FORMAT, TIME_FORMAT, VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)
_warned_names = set()


def is_always_folder(folder_name):
    """Check if this is the reserved folder that plays all the time"""
    return folder_name == ALWAYS_FOLDER


def _start_date(folder_name):
    """When a folder starts. The always folder sorts before every date."""
    schedule = parse_folder_name(folder_name)
    return schedule['start_date'] if schedule else date.min


def parse_folder_name(folder_name):
    """
    Return a folder's schedule as a dict, or None if the name isn't a valid schedule
    'windows' is a list of (start_time, end_time) pairs
    """
    match = re.fullmatch(FOLDER_NAME_PATTERN, folder_name)

    try:
        if match:
            windows = []
            for window in match.group(3).split('_and_'):
                start_time, end_time = window.split('_to_')
                windows.append((datetime.strptime(start_time, TIME_FORMAT).time(),
                                datetime.strptime(end_time, TIME_FORMAT).time()))
            return {
                'start_date': datetime.strptime(match.group(1), DATE_FORMAT).date(),
                'end_date': datetime.strptime(match.group(2), DATE_FORMAT).date(),
                'windows': windows
            }
    except ValueError:
        pass

    _warn_if_mistyped(folder_name)
    return None


def _warn_if_mistyped(folder_name):
    """Warn once about a name that looks like a schedule but isn't, since it won't play"""
    if re.match(r'\d{4}-\d{2}-\d{2}_to_', folder_name) and folder_name not in _warned_names:
        _warned_names.add(folder_name)
        logger.warning(f"Ignoring folder with an invalid schedule name: {folder_name}")


def _in_window(window, schedule, now):
    """Check if a time is inside one daily window of a schedule"""
    start_time, end_time = window
    start_date, end_date = schedule['start_date'], schedule['end_date']
    today, current_time = now.date(), now.time()

    if start_time <= end_time:
        return start_date <= today <= end_date and start_time <= current_time <= end_time

    # Overnight: before midnight it's tonight's window, after midnight it's last night's
    if current_time >= start_time:
        return start_date <= today <= end_date
    if current_time <= end_time:
        return start_date <= today - timedelta(days=1) <= end_date
    return False


def is_folder_active(folder_name, now=None):
    """Check if a folder should be playing at a given time (default: now)"""
    if is_always_folder(folder_name):
        return True

    schedule = parse_folder_name(folder_name)
    if not schedule:
        return False

    now = now or datetime.now()
    return any(_in_window(window, schedule, now) for window in schedule['windows'])


def get_video_files(folder_path):
    """Get all video files from a folder, ignoring hidden files (starting with '.')"""
    video_files = [
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and not f.name.startswith('.')
    ]
    return sorted(video_files)


def video_signature(video_files):
    """Something that changes if a folder's videos change, so the player can restart"""
    signature = []
    for video in video_files:
        try:
            stat = video.stat()
            signature.append((str(video), stat.st_size, stat.st_mtime))
        except OSError:
            signature.append((str(video), None, None))
    return signature


def find_active_folder(videos_path, now=None):
    """
    Find the folder that should be playing at a given time (default: now)
    Returns (folder_path, video_files), or None if nothing should play
    """
    if not videos_path.exists():
        logger.error(f"Videos path {videos_path} does not exist")
        return None

    active_folders = []

    for folder_path in videos_path.iterdir():
        if folder_path.is_dir() and is_folder_active(folder_path.name, now):
            video_files = get_video_files(folder_path)
            if video_files:
                active_folders.append((folder_path, video_files))

    if not active_folders:
        return None

    # If multiple folders are active, use the one with the most recent start date,
    # which puts the always folder last
    active_folders.sort(key=lambda x: _start_date(x[0].name), reverse=True)

    return active_folders[0]


def get_all_valid_folders(videos_path):
    """
    Get all valid video folders regardless of schedule, sorted chronologically
    Returns list of tuples: (folder_path, video_files)
    Ignores folders and files that start with '.'
    """
    if not videos_path.exists():
        return []

    valid_folders = []

    for folder_path in videos_path.iterdir():
        if (folder_path.is_dir() and not folder_path.name.startswith('.')
                and (is_always_folder(folder_path.name) or parse_folder_name(folder_path.name))):
            video_files = get_video_files(folder_path)
            if video_files:
                valid_folders.append((folder_path, video_files))

    # Sort by start date (ascending - chronological order)
    valid_folders.sort(key=lambda x: _start_date(x[0].name))

    return valid_folders
