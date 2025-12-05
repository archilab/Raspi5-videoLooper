# Codebase Cleanup and Improvement Suggestions

## 1. Create a Central Constants Module

**Problem**: Magic numbers, strings, and constants are duplicated across files.

**Solution**: Create `constants.py` to centralize all constants.

```python
# constants.py
"""Central constants for the video looper system"""

# Paths
DEFAULT_VIDEOS_PATH = "/home/looper/videos"
DEFAULT_LOG_FILE = "/var/log/video_looper.log"
DEFAULT_INSTALL_DIR = "/home/looper/video_looper"

# Video formats
VIDEO_EXTENSIONS = frozenset({'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'})

# Projector config files
PROJECTOR_CONFIG_FILES = ['projector.txt', 'projector.conf', 'config.txt']

# Folder naming pattern
FOLDER_NAME_PATTERN = r'(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_(\d{4})_to_(\d{4})'
DATE_FORMAT = '%Y-%m-%d'
TIME_FORMAT = '%H%M'

# Timing
CHECK_INTERVAL = 30
VIDEO_STOP_TIMEOUT = 5
HDMI_WAKE_DELAY = 2

# Serial defaults (Optoma)
DEFAULT_SERIAL_PORT = '/dev/ttyUSB0'
DEFAULT_BAUD_RATE = 9600
DEFAULT_TIMEOUT = 5
DEFAULT_START_COMMAND = '~0000 1'
DEFAULT_STOP_COMMAND = '~0000 0'
```

**Benefits**: 
- Single source of truth
- Easy to update
- Type-safe with `frozenset`
- Better IDE support

---

## 2. Add Type Hints

**Problem**: No type information makes code harder to understand and maintain.

**Solution**: Add type hints throughout (Python 3.6+ compatible).

```python
from typing import Optional, Dict, List, Tuple, Set
from pathlib import Path
from datetime import date, time

def parse_folder_name(self, folder_name: str) -> Optional[Dict[str, Union[date, time]]]:
    """Parse folder name to extract scheduling information"""
    ...

def get_video_files(self, folder_path: Path) -> List[Path]:
    """Get all video files from a folder"""
    ...

def is_folder_active(self, folder_name: str) -> bool:
    """Check if a folder should be active"""
    ...
```

**Benefits**:
- Better IDE autocomplete
- Catch errors earlier
- Self-documenting code
- Easier refactoring

---

## 3. Create Configuration Manager

**Problem**: `config.conf` exists but isn't used. Hard-coded values throughout code.

**Solution**: Create `config_manager.py` to load and validate configuration.

```python
# config_manager.py
"""Configuration management for video looper"""

from pathlib import Path
from typing import Dict, Any
import configparser
from constants import DEFAULT_VIDEOS_PATH, DEFAULT_LOG_FILE

class ConfigManager:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path('/home/looper/video_looper/config.conf')
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file with defaults"""
        config = {
            'videos_path': DEFAULT_VIDEOS_PATH,
            'log_file': DEFAULT_LOG_FILE,
            'check_interval': 30,
            # ... other defaults
        }
        
        if self.config_path.exists():
            # Load from file
            ...
        
        return config
    
    @property
    def videos_path(self) -> Path:
        return Path(self._config['videos_path'])
    
    @property
    def log_file(self) -> str:
        return self._config['log_file']
```

**Benefits**:
- Centralized configuration
- Validation
- Defaults with override capability
- Type-safe access

---

## 4. Extract Folder Name Parser

**Problem**: Folder name parsing logic is embedded in VideoLooper class.

**Solution**: Create dedicated `folder_parser.py` module.

```python
# folder_parser.py
"""Parse and validate folder names for scheduling"""

from typing import Optional, Dict, NamedTuple
from datetime import date, time, datetime
import re
from constants import FOLDER_NAME_PATTERN, DATE_FORMAT, TIME_FORMAT

class ScheduleInfo(NamedTuple):
    start_date: date
    end_date: date
    start_time: time
    end_time: time

class FolderParser:
    @staticmethod
    def parse(folder_name: str) -> Optional[ScheduleInfo]:
        """Parse folder name and return schedule info"""
        pattern = re.compile(FOLDER_NAME_PATTERN)
        match = pattern.match(folder_name)
        
        if not match:
            return None
        
        try:
            return ScheduleInfo(
                start_date=datetime.strptime(match.group(1), DATE_FORMAT).date(),
                end_date=datetime.strptime(match.group(2), DATE_FORMAT).date(),
                start_time=datetime.strptime(match.group(3), TIME_FORMAT).time(),
                end_time=datetime.strptime(match.group(4), TIME_FORMAT).time()
            )
        except ValueError:
            return None
    
    @staticmethod
    def is_active(schedule: ScheduleInfo, now: Optional[datetime] = None) -> bool:
        """Check if schedule is currently active"""
        if now is None:
            now = datetime.now()
        
        current_date = now.date()
        current_time = now.time()
        
        if not (schedule.start_date <= current_date <= schedule.end_date):
            return False
        
        start_datetime = datetime.combine(now.date(), schedule.start_time)
        end_datetime = datetime.combine(now.date(), schedule.end_time)
        current_datetime = datetime.combine(now.date(), current_time)
        
        return start_datetime <= current_datetime <= end_datetime
```

**Benefits**:
- Single responsibility
- Testable in isolation
- Reusable
- Clear data structure with NamedTuple

---

## 5. Standardize Error Handling

**Problem**: Inconsistent error handling patterns across modules.

**Solution**: Create custom exceptions and consistent error handling.

```python
# exceptions.py
"""Custom exceptions for video looper"""

class VideoLooperError(Exception):
    """Base exception for video looper"""
    pass

class VideoLooperConfigError(VideoLooperError):
    """Configuration related errors"""
    pass

class VideoLooperConnectionError(VideoLooperError):
    """Connection related errors (projector, HDMI)"""
    pass

class VideoLooperSyncError(VideoLooperError):
    """USB sync related errors"""
    pass
```

**Usage**:
```python
try:
    self.projector.connect()
except VideoLooperConnectionError as e:
    self.logger.error(f"Projector connection failed: {e}")
    # Handle gracefully
```

**Benefits**:
- Clear error types
- Better error handling
- Easier debugging
- Consistent error messages

---

## 6. Improve File Organization

**Problem**: All logic mixed in single files.

**Solution**: Better module organization.

```
video_looper/
├── __init__.py
├── constants.py          # All constants
├── exceptions.py         # Custom exceptions
├── config_manager.py     # Configuration handling
├── folder_parser.py      # Folder name parsing
├── video_looper.py       # Main video looper class
├── controllers/
│   ├── __init__.py
│   ├── projector.py      # ProjectorController
│   ├── hdmi.py           # HDMIController
│   └── time_sync.py      # TimeSyncManager
└── sync/
    ├── __init__.py
    └── usb_sync.py       # USBSync
```

**Benefits**:
- Clear structure
- Easy to navigate
- Scalable
- Better imports

---

## 7. Add Dataclasses for Complex Data

**Problem**: Dictionaries for structured data lack type safety.

**Solution**: Use dataclasses (Python 3.7+) or NamedTuple.

```python
from dataclasses import dataclass
from typing import List
from pathlib import Path

@dataclass
class ActiveFolder:
    path: Path
    video_files: List[Path]
    schedule: ScheduleInfo
    
    def has_videos(self) -> bool:
        return len(self.video_files) > 0
```

**Benefits**:
- Type safety
- Better IDE support
- Immutability option
- Self-documenting

---

## 8. Consolidate Video File Operations

**Problem**: Video file checking logic duplicated in multiple places.

**Solution**: Create `video_utils.py` utility module.

```python
# video_utils.py
"""Utility functions for video file operations"""

from pathlib import Path
from typing import List
from constants import VIDEO_EXTENSIONS

def get_video_files(folder_path: Path) -> List[Path]:
    """Get all video files from a folder"""
    return sorted([
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ])

def has_video_files(folder_path: Path) -> bool:
    """Check if folder contains video files"""
    return len(get_video_files(folder_path)) > 0
```

**Benefits**:
- DRY principle
- Consistent behavior
- Easy to test
- Centralized logic

---

## 9. Improve Docstrings

**Problem**: Some methods lack clear documentation.

**Solution**: Use Google-style or NumPy-style docstrings consistently.

```python
def find_active_folder(self) -> Optional[ActiveFolder]:
    """
    Find the currently active video folder based on date/time.
    
    Returns:
        ActiveFolder if an active folder is found, None otherwise.
        If multiple folders are active, returns the one with the
        most recent start date.
        
    Example:
        >>> looper = VideoLooper()
        >>> folder = looper.find_active_folder()
        >>> if folder:
        ...     print(f"Playing: {folder.path.name}")
    """
```

**Benefits**:
- Clear documentation
- Better IDE tooltips
- Auto-generated docs
- Examples for complex methods

---

## 10. Add Logging Configuration Module

**Problem**: Logging setup duplicated, inconsistent levels.

**Solution**: Centralize logging configuration.

```python
# logger_config.py
"""Centralized logging configuration"""

import logging
import sys
from pathlib import Path
from typing import Optional

def setup_logger(
    name: str,
    log_file: Optional[Path] = None,
    level: int = logging.WARNING,
    format_string: Optional[str] = None
) -> logging.Logger:
    """
    Set up logger with consistent configuration.
    
    Args:
        name: Logger name (typically __name__)
        log_file: Optional log file path
        level: Logging level (default: WARNING)
        format_string: Optional custom format string
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    formatter = logging.Formatter(format_string)
    
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
```

**Benefits**:
- Consistent logging
- Easy to change globally
- Better log formatting
- Centralized control

---

## 11. Use Enum for Magic Strings

**Problem**: Magic strings used for state/status values.

**Solution**: Use Enums for better type safety.

```python
from enum import Enum, auto

class ProjectorState(Enum):
    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    RUNNING = "running"

class HDMIState(Enum):
    STANDBY = 0
    ON = 1
```

**Benefits**:
- Type safety
- IDE autocomplete
- Prevent typos
- Clear valid values

---

## 12. Extract VLC Command Builder

**Problem**: VLC command construction embedded in video_looper.py.

**Solution**: Create VLC command builder class.

```python
# vlc_builder.py
"""Build VLC command lines"""

from typing import List
from pathlib import Path

class VLCCommandBuilder:
    """Build cvlc command lines for video playback"""
    
    BASE_ARGS = [
        'cvlc',
        '--intf', 'dummy',
        '--fullscreen',
        '--loop',
        '--no-osd',
        '--no-audio',
        '--quiet'
    ]
    
    @classmethod
    def build(cls, video_files: List[Path]) -> List[str]:
        """Build VLC command for given video files"""
        return cls.BASE_ARGS + [str(f) for f in video_files]
```

**Benefits**:
- Single responsibility
- Easy to modify VLC options
- Testable
- Reusable

---

## Priority Implementation Order

1. **High Priority** (Quick wins):
   - ✅ Create `constants.py` (removes duplication immediately)
   - ✅ Extract `video_utils.py` (removes code duplication)
   - ✅ Create `exceptions.py` (improves error handling)

2. **Medium Priority** (Structure improvements):
   - ✅ Create `folder_parser.py` (better separation of concerns)
   - ✅ Add type hints gradually (improves maintainability)
   - ✅ Improve docstrings (better documentation)

3. **Low Priority** (Nice to have):
   - ✅ Reorganize file structure (packages)
   - ✅ Add dataclasses (if Python 3.7+)
   - ✅ Create configuration manager (if config file needed)

---

## Quick Start: Constants Module

Here's a ready-to-use `constants.py` you can implement immediately:

```python
#!/usr/bin/env python3
"""Central constants for video looper system"""

from typing import FrozenSet

# Paths
DEFAULT_VIDEOS_PATH = "/home/looper/videos"
DEFAULT_LOG_FILE = "/var/log/video_looper.log"
DEFAULT_INSTALL_DIR = "/home/looper/video_looper"

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
```

Then update imports:
```python
# In video_looper.py, usb_sync.py, etc.
from constants import VIDEO_EXTENSIONS, PROJECTOR_CONFIG_FILES
```

---

## Summary

These improvements will make your codebase:
- ✅ **More maintainable**: Single source of truth for constants
- ✅ **More readable**: Type hints and better documentation
- ✅ **More testable**: Separated concerns, utility functions
- ✅ **More scalable**: Clear structure, better organization
- ✅ **Less error-prone**: Type safety, Enums, validation

Start with the constants module - it provides immediate value with minimal changes!

