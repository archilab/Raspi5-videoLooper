#!/usr/bin/env python3
"""Central constants for video looper system"""

from typing import FrozenSet

# Paths
DEFAULT_VIDEOS_PATH = "/home/looper/videos"
DEFAULT_LOG_FILE = "/var/log/video_looper.log"
DEFAULT_INSTALL_DIR = "/home/looper/video_looper"
# Locked by the boot menu while the time is being entered; in RAM, so no SD card writes
TIME_ENTRY_LOCK_FILE = "/dev/shm/video_looper_time_entry.lock"
# The menu has no permission to change the clock, so it asks the service through these
TIME_SET_REQUEST_FILE = "/dev/shm/video_looper_time_request"
TIME_SET_RESULT_FILE = "/dev/shm/video_looper_time_result"
TIME_SET_TIMEOUT = 20  # seconds the menu waits for the service to answer

# Video formats
VIDEO_EXTENSIONS: FrozenSet[str] = frozenset({
    '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'
})

# Projector configuration files
PROJECTOR_CONFIG_FILES = ['projector.txt', 'projector.conf', 'config.txt']

# Folder naming
FOLDER_NAME_PATTERN = r'(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_(\d{4})_to_(\d{4})'
DATE_FORMAT = '%Y-%m-%d'
TIME_FORMAT = '%H%M'

# Timing constants
CHECK_INTERVAL = 30  # seconds
VIDEO_STOP_TIMEOUT = 5  # seconds
HDMI_WAKE_DELAY = 2  # seconds

# Serial communication defaults (Optoma)
DEFAULT_SERIAL_PORT = '/dev/ttyUSB0'
DEFAULT_BAUD_RATE = 9600
DEFAULT_SERIAL_TIMEOUT = 5
DEFAULT_START_COMMAND = '~0000 1'
DEFAULT_STOP_COMMAND = '~0000 0'

# USB mount points (priority order)
USB_MOUNT_POINTS = [
    '/media/usb0',
    '/media/usb1',
    '/media/usb2',
    '/media/usb3'
]

# Test mode constants
TEST_MODE_KEY_CTRL = 29  # Left Ctrl key code (Linux input event)
TEST_MODE_KEY_F1 = 59   # F1 key code (Linux input event)
TEST_PLAY_DURATION = 60  # seconds - 1 minute per folder
TEST_PAUSE_DURATION = 30  # seconds - pause between folders

