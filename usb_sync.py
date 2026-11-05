#!/usr/bin/env python3
"""
USB Drive Sync Module
Synchronizes video folders between USB drive and local videos directory on boot
"""

import os
import pwd
import logging
import shutil
import time
from pathlib import Path
import re
from datetime import datetime
from console import show_on_console
from constants import (
    VIDEO_EXTENSIONS, PROJECTOR_CONFIG_FILES, FOLDER_NAME_PATTERN,
    DATE_FORMAT, TIME_FORMAT, USB_MOUNT_POINTS, DEFAULT_VIDEOS_PATH
)

class USBSync:
    def __init__(self, local_videos_path=None):
        self.logger = logging.getLogger(__name__)
        self.local_videos_path = Path(local_videos_path or DEFAULT_VIDEOS_PATH)
    
    def display_message_on_screen(self, message):
        """Display a message on the HDMI screen (TTY1)"""
        show_on_console(f"\n\n{message}\n\n")

    def _set_looper_owner(self, path):
        """Give a copied file to the looper user, in case this runs as root"""
        try:
            looper_user = pwd.getpwnam('looper')
            uid, gid = looper_user.pw_uid, looper_user.pw_gid
        except KeyError:
            uid, gid = 1000, 1000
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass
        
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
            usbmount_paths = [Path(p) for p in USB_MOUNT_POINTS]
            
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
            except OSError as e:
                self.logger.warning(f"Could not read /proc/mounts: {e}")
            
        except OSError as e:
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
        
        # Skip hidden folders (starting with '.')
        if folder_path.name.startswith('.'):
            return False
        
        # Check folder name pattern
        match = re.match(FOLDER_NAME_PATTERN, folder_path.name)
        
        if not match:
            return False
        
        # Validate date format
        try:
            datetime.strptime(match.group(1), DATE_FORMAT).date()
            datetime.strptime(match.group(2), DATE_FORMAT).date()
            datetime.strptime(match.group(3), TIME_FORMAT).time()
            datetime.strptime(match.group(4), TIME_FORMAT).time()
        except ValueError:
            return False
        
        # Check if folder contains at least one video file
        try:
            for file_path in folder_path.iterdir():
                # Skip hidden files (starting with '.')
                if file_path.name.startswith('.'):
                    continue
                if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
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
                # Skip hidden folders (starting with '.')
                if item.name.startswith('.'):
                    continue
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
                # Skip hidden files (starting with '.')
                if item.name.startswith('.'):
                    continue
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
                # Skip hidden files (starting with '.')
                if item.name.startswith('.'):
                    continue
                if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
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
    
    def _copy_file_safely(self, source, destination):
        """
        Copy a file so that destination is only ever the old file or the complete new one.
        An interruption leaves just a hidden temp file, which the next sync removes.
        """
        temp_file = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copy2(source, temp_file)
            with open(temp_file, 'rb') as f:
                os.fsync(f.fileno())  # On disk before the rename, in case power is lost
            self._set_looper_owner(temp_file)
            os.replace(temp_file, destination)
        except OSError:
            temp_file.unlink(missing_ok=True)
            raise

    def sync_folder(self, usb_folder_path, local_folder_path):
        """
        Sync a folder from USB to local directory
        Copies missing files, updates changed ones, and removes videos and
        projector configs that are no longer on the USB drive
        Args:
            usb_folder_path: Source folder on USB
            local_folder_path: Destination folder (local)
        Returns:
            tuple: (copied_count, updated_count, errors)
        """
        copied_count = 0
        updated_count = 0
        errors = []

        try:
            local_folder_path.mkdir(parents=True, exist_ok=True)
            # Left by a sync that was interrupted
            for stale_file in local_folder_path.glob('.*.tmp'):
                stale_file.unlink()
        except OSError as e:
            errors.append(f"Failed to prepare local folder {local_folder_path.name}: {e}")
            return (copied_count, updated_count, errors)

        usb_files = self.get_folder_files_dict(usb_folder_path)
        local_files = self.get_folder_files_dict(local_folder_path)

        for filename, usb_file in usb_files.items():
            local_file = local_folder_path / filename
            try:
                if filename in local_files:
                    usb_stat = usb_file.stat()
                    local_stat = local_file.stat()
                    if (usb_stat.st_mtime <= local_stat.st_mtime and
                            usb_stat.st_size == local_stat.st_size):
                        continue

                self._copy_file_safely(usb_file, local_file)
                if filename in local_files:
                    updated_count += 1
                else:
                    copied_count += 1
            except OSError as e:
                errors.append(f"Failed to copy {filename}: {e}")

        # Only remove old files once the new ones are safely in place
        if not errors:
            for filename, local_file in local_files.items():
                if filename not in usb_files and (local_file.suffix.lower() in VIDEO_EXTENSIONS or
                                                  filename in PROJECTOR_CONFIG_FILES):
                    try:
                        local_file.unlink()
                    except OSError as e:
                        errors.append(f"Failed to delete file {filename}: {e}")

        return (copied_count, updated_count, errors)
    
    def plan_sync(self, usb_root_path):
        """
        Work out what syncing from a USB drive would do, without changing anything.
        Both the real sync and its preview use this, so they can't disagree.
        Returns:
            dict: 'update' and 'copy' lists of folder names, 'rename' list of
            (old name, new name), and 'delete' list of local folder names
        """
        usb_folders = self.get_valid_folders(usb_root_path)
        local_folders = self.get_valid_folders(self.local_videos_path)

        # Local folders that are going away. Only these may be renamed, since a folder
        # that's still on the drive must stay, even if another one has the same videos.
        leaving = {name: path for name, path in sorted(local_folders.items())
                   if name not in usb_folders}
        plan = {'update': [], 'copy': [], 'rename': [], 'delete': []}

        for name, usb_folder in sorted(usb_folders.items()):
            if name in local_folders:
                plan['update'].append(name)
                continue
            old_name, _ = self.find_folder_with_same_videos(usb_folder, leaving)
            if old_name:
                del leaving[old_name]
                plan['rename'].append((old_name, name))
            else:
                plan['copy'].append(name)

        plan['delete'] = sorted(leaving)
        return plan

    def sync_usb_to_local(self, usb_root_path):
        """
        Sync all valid video folders from USB drive to local directory
        Args:
            usb_root_path: Root path of USB drive
        Returns:
            bool: True if sync was successful, False otherwise
        """
        usb_root_path = Path(usb_root_path)
        plan = self.plan_sync(usb_root_path)
        folder_count = len(plan['update']) + len(plan['copy']) + len(plan['rename'])
        if not folder_count:
            return False

        try:
            self.local_videos_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.error(f"Failed to create local videos directory: {e}")
            return False

        self.display_message_on_screen(
            f"USB Sync Started\nCopying {folder_count} folder(s) from USB drive..."
        )

        total_copied = 0
        total_updated = 0
        total_renamed = 0
        total_errors = []

        # Renames first, so their files don't get copied again
        for old_name, new_name in plan['rename']:
            try:
                (self.local_videos_path / old_name).rename(self.local_videos_path / new_name)
                total_renamed += 1
            except OSError as e:
                total_errors.append(f"Failed to rename folder {old_name}: {e}")

        # Syncing also picks up any differences in renamed folders, and copies them if the rename failed
        for name in plan['update'] + plan['copy'] + [new_name for _, new_name in plan['rename']]:
            copied, updated, errors = self.sync_folder(usb_root_path / name, self.local_videos_path / name)
            total_copied += copied
            total_updated += updated
            total_errors.extend(errors)

        # Only delete old folders if the new ones arrived safely, so a full disk
        # or a failing drive can't leave the player with nothing
        if total_errors:
            if plan['delete']:
                self.logger.warning(f"Keeping old folders because of sync errors: {plan['delete']}")
        else:
            for name in plan['delete']:
                try:
                    shutil.rmtree(self.local_videos_path / name)
                except OSError as e:
                    total_errors.append(f"Failed to delete folder {name}: {e}")

        for error in total_errors:
            self.logger.error(f"USB sync: {error}")

        summary = (
            f"Copied: {total_copied} file(s)\n"
            f"Updated: {total_updated} file(s)\n"
            f"Renamed: {total_renamed} folder(s)"
        )
        if total_errors:
            self.display_message_on_screen(
                f"USB Sync Completed with Errors\n{summary}\nErrors: {len(total_errors)}"
            )
            time.sleep(5)
        elif total_copied or total_updated or total_renamed:
            self.display_message_on_screen(f"USB Sync Completed Successfully\n{summary}")
            time.sleep(5)
        else:
            self.display_message_on_screen("USB Sync Completed\nNo changes needed")
            time.sleep(3)

        return not total_errors
    
    def find_sync_source(self, usb_mounts):
        """Pick the USB drive to sync from: the first one with valid video folders"""
        for usb_mount in usb_mounts:
            if self.get_valid_folders(usb_mount):
                return usb_mount
        return None

    def sync_on_boot(self):
        """
        Check for USB drives on boot and sync if found
        Returns:
            bool: True if USB was found and synced, False otherwise
        """
        time.sleep(2)

        source = self.find_sync_source(self.find_usb_drives())
        if source is None:
            return False
        if not self.sync_usb_to_local(source):
            self.logger.warning(f"USB sync completed with errors from {source}")
        return True


