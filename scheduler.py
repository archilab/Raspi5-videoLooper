#!/usr/bin/env python3
"""
Decides what should play, from folder names in the videos directory
Format: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM
Example: 2024-01-01_to_2024-01-31_0900_to_1800

If the end time is before the start time the window runs overnight. It starts on each
date in the range, so the last night continues into the morning after the end date:
2024-01-01_to_2024-01-03_2200_to_0600 plays from 22:00 on Jan 1 until 06:00 on Jan 4.
"""

import logging
import re
from datetime import datetime, timedelta
from constants import FOLDER_NAME_PATTERN, DATE_FORMAT, TIME_FORMAT, VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


def parse_folder_name(folder_name):
    """Return a folder's schedule as a dict, or None if the name isn't a valid schedule"""
    match = re.match(FOLDER_NAME_PATTERN, folder_name)

    if not match:
        return None

    try:
        return {
            'start_date': datetime.strptime(match.group(1), DATE_FORMAT).date(),
            'end_date': datetime.strptime(match.group(2), DATE_FORMAT).date(),
            'start_time': datetime.strptime(match.group(3), TIME_FORMAT).time(),
            'end_time': datetime.strptime(match.group(4), TIME_FORMAT).time()
        }
    except ValueError:
        return None


def is_folder_active(folder_name, now=None):
    """Check if a folder should be playing at a given time (default: now)"""
    schedule = parse_folder_name(folder_name)
    if not schedule:
        return False

    now = now or datetime.now()
    today, current_time = now.date(), now.time()
    start_date, end_date = schedule['start_date'], schedule['end_date']
    start_time, end_time = schedule['start_time'], schedule['end_time']

    if start_time <= end_time:
        return start_date <= today <= end_date and start_time <= current_time <= end_time

    # Overnight: before midnight it's tonight's window, after midnight it's last night's
    if current_time >= start_time:
        return start_date <= today <= end_date
    if current_time <= end_time:
        return start_date <= today - timedelta(days=1) <= end_date
    return False


def get_video_files(folder_path):
    """Get all video files from a folder, ignoring hidden files (starting with '.')"""
    video_files = [
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and not f.name.startswith('.')
    ]
    return sorted(video_files)


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

    # If multiple folders are active, use the one with the most recent start date
    active_folders.sort(key=lambda x: parse_folder_name(x[0].name)['start_date'], reverse=True)

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
                and parse_folder_name(folder_path.name)):
            video_files = get_video_files(folder_path)
            if video_files:
                valid_folders.append((folder_path, video_files))

    # Sort by start date (ascending - chronological order)
    valid_folders.sort(key=lambda x: parse_folder_name(x[0].name)['start_date'])

    return valid_folders
