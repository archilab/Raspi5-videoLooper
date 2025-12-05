#!/usr/bin/env python3
"""
USB Drive Sync Module
Synchronizes video folders between USB drive and local videos directory on boot
"""

import os
import sys
import logging
import shutil
from pathlib import Path
import re
from datetime import datetime
import subprocess

class USBSync:
    def __init__(self, local_videos_path="/home/looper/videos", log_file="/var/log/video_looper.log"):
        self.logger = logging.getLogger(__name__)
        self.local_videos_path = Path(local_videos_path)
        self.log_file = log_file
        self.video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
        
    def find_usb_drives(self):
        """
        Find mounted USB drives
        Returns:
            list: List of paths to potential USB mount points
        """
        usb_mounts = []
        
        try:
            # Priority 1: Check usbmount mount points first (/media/usb0, /media/usb1, etc.)
            # These are the standard locations for automatically mounted USB drives
            usbmount_paths = [
                Path('/media/usb0'),
                Path('/media/usb1'),
                Path('/media/usb2'),
                Path('/media/usb3'),
            ]
            
            for usb_path in usbmount_paths:
                if usb_path.exists() and usb_path.is_dir():
                    try:
                        # Check if it's actually mounted
                        if os.path.ismount(usb_path):
                            usb_mounts.append(usb_path)
                    except (PermissionError, OSError):
                        pass
            
            # Priority 2: Check other common USB mount locations
            # /media/<user>/ - user-mounted USB drives
            # /mnt/usb* - system-mounted USB drives
            # /run/media/<user>/* - systemd-mounted USB drives
            
            potential_paths = [
                Path('/media/looper'),
                Path('/mnt'),
                Path('/run/media/looper'),
                Path('/media'),
            ]
            
            for base_path in potential_paths:
                if base_path.exists() and base_path.is_dir():
                    try:
                        # Check all subdirectories for mounted drives
                        for item in base_path.iterdir():
                            # Skip usbmount paths we already checked
                            if item in usb_mounts:
                                continue
                            
                            if item.is_dir() and os.path.ismount(item):
                                usb_mounts.append(item)
                    except (PermissionError, OSError):
                        pass
            
            # Priority 3: Also check /proc/mounts for mounted USB devices
            # This catches any other mount points we might have missed
            try:
                with open('/proc/mounts', 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            mount_point = parts[1]
                            mount_path = Path(mount_point)
                            
                            # Skip if already in our list
                            if mount_path in usb_mounts:
                                continue
                            
                            # Check if it's a USB device mount (but skip /media/usb* if already checked)
                            if any(keyword in mount_point for keyword in ['/media/usb', '/mnt/usb', '/run/media/']):
                                if mount_path.exists() and mount_path.is_dir():
                                    # Additional check: skip if it's a usbmount path we already processed
                                    is_usbmount = False
                                    try:
                                        is_usbmount = any(
                                            usb_path.exists() and usb_path.samefile(mount_path)
                                            for usb_path in usbmount_paths
                                        )
                                    except OSError:
                                        # samefile can fail if paths don't exist, just continue
                                        pass
                                    
                                    if not is_usbmount:
                                        usb_mounts.append(mount_path)
            except Exception:
                pass
            
        except Exception as e:
            self.logger.error(f"Error finding USB drives: {e}")
        
        # Sort to ensure usbmount paths come first
        sorted_mounts = []
        for usb_path in usbmount_paths:
            if usb_path in usb_mounts:
                sorted_mounts.append(usb_path)
        # Add any other mounts that aren't usbmount paths
        for mount in usb_mounts:
            if mount not in sorted_mounts:
                sorted_mounts.append(mount)
        
        return sorted_mounts
    
    def is_valid_video_folder(self, folder_path):
        """
        Check if a folder is a valid video folder
        Valid folder must:
        1. Match the naming pattern: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM
        2. Contain at least one video file
        Args:
            folder_path: Path to folder to check
        Returns:
            bool: True if valid, False otherwise
        """
        if not folder_path.is_dir():
            return False
        
        # Check folder name pattern
        pattern = r'(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_(\d{4})_to_(\d{4})'
        match = re.match(pattern, folder_path.name)
        
        if not match:
            return False
        
        # Validate date format
        try:
            datetime.strptime(match.group(1), '%Y-%m-%d').date()
            datetime.strptime(match.group(2), '%Y-%m-%d').date()
            datetime.strptime(match.group(3), '%H%M').time()
            datetime.strptime(match.group(4), '%H%M').time()
        except ValueError:
            return False
        
        # Check if folder contains at least one video file
        try:
            for file_path in folder_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in self.video_extensions:
                    return True
        except (PermissionError, OSError):
            return False
        
        return False
    
    def get_valid_folders(self, root_path):
        """
        Get all valid video folders from a root path
        Args:
            root_path: Path to search for folders
        Returns:
            dict: Dictionary mapping folder names to folder paths
        """
        valid_folders = {}
        
        if not root_path.exists() or not root_path.is_dir():
            return valid_folders
        
        try:
            for item in root_path.iterdir():
                if item.is_dir() and self.is_valid_video_folder(item):
                    valid_folders[item.name] = item
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not access {root_path}: {e}")
        
        return valid_folders
    
    def get_folder_files_dict(self, folder_path):
        """
        Get a dictionary of files in a folder (name -> Path)
        Args:
            folder_path: Path to folder
        Returns:
            dict: Dictionary mapping file names to file paths
        """
        files_dict = {}
        
        if not folder_path.exists() or not folder_path.is_dir():
            return files_dict
        
        try:
            for item in folder_path.iterdir():
                if item.is_file():
                    files_dict[item.name] = item
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not list files in {folder_path}: {e}")
        
        return files_dict
    
    def get_video_files_set(self, folder_path):
        """
        Get a set of video file names from a folder
        Args:
            folder_path: Path to folder
        Returns:
            set: Set of video file names (case-insensitive)
        """
        video_files = set()
        
        if not folder_path.exists() or not folder_path.is_dir():
            return video_files
        
        try:
            for item in folder_path.iterdir():
                if item.is_file() and item.suffix.lower() in self.video_extensions:
                    video_files.add(item.name.lower())
        except (PermissionError, OSError) as e:
            self.logger.warning(f"Could not list video files in {folder_path}: {e}")
        
        return video_files
    
    def folders_have_same_video_files(self, folder1_path, folder2_path):
        """
        Check if two folders have the same video files (by filename)
        Args:
            folder1_path: Path to first folder
            folder2_path: Path to second folder
        Returns:
            bool: True if folders have the same video files, False otherwise
        """
        video_files1 = self.get_video_files_set(folder1_path)
        video_files2 = self.get_video_files_set(folder2_path)
        
        # Both folders must have at least one video file
        if not video_files1 or not video_files2:
            return False
        
        # Check if video file sets are identical
        return video_files1 == video_files2
    
    def find_folder_with_same_videos(self, usb_folder_path, local_folders):
        """
        Find a local folder that has the same video files as the USB folder
        Args:
            usb_folder_path: Path to USB folder
            local_folders: Dictionary of local folders (name -> Path)
        Returns:
            tuple: (folder_name, folder_path) if found, (None, None) otherwise
        """
        usb_video_files = self.get_video_files_set(usb_folder_path)
        
        if not usb_video_files:
            return (None, None)
        
        # Check each local folder
        for folder_name, local_folder_path in local_folders.items():
            if self.folders_have_same_video_files(usb_folder_path, local_folder_path):
                return (folder_name, local_folder_path)
        
        return (None, None)
    
    def sync_folder(self, usb_folder_path, local_folder_path):
        """
        Sync a folder from USB to local directory
        Copies missing files and updates existing ones
        Args:
            usb_folder_path: Source folder on USB
            local_folder_path: Destination folder (local)
        Returns:
            tuple: (copied_count, updated_count, errors)
        """
        copied_count = 0
        updated_count = 0
        errors = []
        
        # Ensure local folder exists
        try:
            local_folder_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Failed to create local folder: {e}")
            return (copied_count, updated_count, errors)
        
        # Get files from both folders
        usb_files = self.get_folder_files_dict(usb_folder_path)
        local_files = self.get_folder_files_dict(local_folder_path)
        
        # Copy/update files from USB to local
        for filename, usb_file in usb_files.items():
            local_file = local_folder_path / filename
            
            try:
                # Check if file needs to be copied/updated
                should_copy = False
                if not local_file.exists():
                    should_copy = True
                else:
                    usb_stat = usb_file.stat()
                    local_stat = local_file.stat()
                    if (usb_stat.st_mtime > local_stat.st_mtime or 
                        usb_stat.st_size != local_stat.st_size):
                        should_copy = True
                
                if should_copy:
                    shutil.copy2(usb_file, local_file)
                    try:
                        import pwd
                        looper_user = pwd.getpwnam('looper')
                        os.chown(local_file, looper_user.pw_uid, looper_user.pw_gid)
                    except (KeyError, ImportError, PermissionError):
                        try:
                            os.chown(local_file, 1000, 1000)
                        except Exception:
                            pass
                    
                    if filename in local_files:
                        updated_count += 1
                    else:
                        copied_count += 1
            except Exception as e:
                error_msg = f"Failed to copy {filename}: {e}"
                errors.append(error_msg)
                self.logger.error(error_msg)
        
        # Copy projector config files if they exist
        config_files = ['projector.txt', 'projector.conf', 'config.txt']
        for config_file in config_files:
            usb_config = usb_folder_path / config_file
            local_config = local_folder_path / config_file
            
            if usb_config.exists():
                try:
                    shutil.copy2(usb_config, local_config)
                    try:
                        import pwd
                        looper_user = pwd.getpwnam('looper')
                        os.chown(local_config, looper_user.pw_uid, looper_user.pw_gid)
                    except (KeyError, ImportError, PermissionError):
                        try:
                            os.chown(local_config, 1000, 1000)
                        except Exception:
                            pass
                    pass
                except Exception:
                    pass
            elif local_config.exists():
                try:
                    local_config.unlink()
                except Exception:
                    pass
        
        # Delete local files that are not on USB
        for filename, local_file in local_files.items():
            if filename not in usb_files:
                try:
                    # Only delete video files and config files, not other files
                    if (local_file.suffix.lower() in self.video_extensions or 
                        local_file.name in config_files):
                        local_file.unlink()
                except Exception as e:
                    error_msg = f"Failed to delete file {filename}: {e}"
                    errors.append(error_msg)
                    self.logger.warning(error_msg)
        
        return (copied_count, updated_count, errors)
    
    def sync_usb_to_local(self, usb_root_path):
        """
        Sync all valid video folders from USB drive to local directory
        Args:
            usb_root_path: Root path of USB drive
        Returns:
            bool: True if sync was successful, False otherwise
        """
        usb_folders = self.get_valid_folders(usb_root_path)
        if not usb_folders:
            return False
        
        local_folders = self.get_valid_folders(self.local_videos_path)
        
        # Ensure local videos directory exists
        try:
            self.local_videos_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.logger.error(f"Failed to create local videos directory: {e}")
            return False
        
        # Sync folders: copy/update from USB or rename existing folders
        total_copied = 0
        total_updated = 0
        total_renamed = 0
        total_errors = []
        renamed_folders = set()  # Track folders that were renamed
        
        for folder_name, usb_folder in usb_folders.items():
            local_folder = self.local_videos_path / folder_name
            
            if folder_name in local_folders:
                copied, updated, errors = self.sync_folder(usb_folder, local_folder)
                total_copied += copied
                total_updated += updated
                total_errors.extend(errors)
            else:
                # Folder doesn't exist - check if there's a folder with same video files
                # Exclude folders that were already renamed in this sync operation
                folders_to_check = {
                    name: path for name, path in local_folders.items() 
                    if name not in renamed_folders
                }
                existing_folder_name, existing_folder_path = self.find_folder_with_same_videos(
                    usb_folder, folders_to_check
                )
                
                if existing_folder_name and existing_folder_path:
                    try:
                        new_folder_path = self.local_videos_path / folder_name
                        existing_folder_path.rename(new_folder_path)
                        
                        # Update local_folders dict to reflect the rename
                        del local_folders[existing_folder_name]
                        local_folders[folder_name] = new_folder_path
                        renamed_folders.add(existing_folder_name)
                        renamed_folders.add(folder_name)
                        
                        # Now sync files (in case there are differences or new files)
                        copied, updated, errors = self.sync_folder(usb_folder, new_folder_path)
                        total_copied += copied
                        total_updated += updated
                        total_errors.extend(errors)
                        
                        total_renamed += 1
                    except Exception as e:
                        error_msg = f"Failed to rename folder: {e}"
                        total_errors.append(error_msg)
                        self.logger.error(error_msg)
                        copied, updated, errors = self.sync_folder(usb_folder, local_folder)
                        total_copied += copied
                        total_updated += updated
                        total_errors.extend(errors)
                else:
                    copied, updated, errors = self.sync_folder(usb_folder, local_folder)
                    total_copied += copied
                    total_updated += updated
                    total_errors.extend(errors)
        
        # Delete local folders that are not on USB (excluding renamed folders)
        folders_to_delete = []
        for folder_name, local_folder in local_folders.items():
            if folder_name not in usb_folders and folder_name not in renamed_folders:
                folders_to_delete.append((folder_name, local_folder))
        
        if folders_to_delete:
            for folder_name, local_folder in folders_to_delete:
                try:
                    shutil.rmtree(local_folder)
                except Exception as e:
                    error_msg = f"Failed to delete folder {folder_name}: {e}"
                    total_errors.append(error_msg)
                    self.logger.error(error_msg)
        
        if total_errors:
            self.logger.warning(f"  - Errors: {len(total_errors)}")
            for error in total_errors:
                self.logger.warning(f"    {error}")
        
        return len(total_errors) == 0
    
    def check_rtc_time_file(self, usb_mount):
        """
        Check for RTC time file on USB drive and set RTC if found
        Args:
            usb_mount: Path to USB mount point
        Returns:
            bool: True if RTC time file was found and set, False otherwise
        """
        try:
            # Import here to avoid circular imports
            try:
                from time_sync import TimeSyncManager
            except ImportError as e:
                self.logger.error(f"Could not import TimeSyncManager: {e}")
                return False
            
            # Common RTC time file names
            rtc_file_names = ['rtc_time.txt', 'time.txt', 'set_time.txt', 'rtc_time', 'rtc_time.txt']
            
            for rtc_file_name in rtc_file_names:
                rtc_file_path = Path(usb_mount) / rtc_file_name
                
                if rtc_file_path.exists() and rtc_file_path.is_file():
                    time_sync = TimeSyncManager(self.log_file)
                    if time_sync.set_rtc_from_file(str(rtc_file_path)):
                        return True
                    else:
                        self.logger.warning(f"Failed to set RTC time from file: {rtc_file_path}")
                        return False
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking RTC time file: {e}")
            return False
    
    def sync_on_boot(self):
        """
        Check for USB drives on boot and sync if found
        Also checks for RTC time file on USB drive
        Returns:
            bool: True if USB was found and synced, False otherwise
        """
        import time
        time.sleep(2)
        
        usb_mounts = self.find_usb_drives()
        if not usb_mounts:
            return False
        
        rtc_set = False
        for usb_mount in usb_mounts:
            if self.check_rtc_time_file(usb_mount):
                rtc_set = True
                break
        
        for usb_mount in usb_mounts:
            valid_folders = self.get_valid_folders(usb_mount)
            if valid_folders:
                success = self.sync_usb_to_local(usb_mount)
                if not success:
                    self.logger.warning(f"USB sync completed with errors from {usb_mount}")
                return True
            elif not rtc_set:
                self.check_rtc_time_file(usb_mount)
        
        return False


