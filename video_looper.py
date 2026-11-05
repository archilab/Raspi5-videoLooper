#!/usr/bin/env python3
"""
Raspberry Pi 5 Video Looper with VLC
Plays videos according to a schedule in their folder names (see scheduler.py).
This is the service's main loop and the command line.
"""

import sys
import time
import logging
from pathlib import Path
import signal
import scheduler
import time_entry
from boot_menu import BootMenu
from hdmi_controller import HDMIController
from player import Player
from projector_controller import ProjectorController
from time_sync import TimeSyncManager
from usb_sync import USBSync
from constants import DEFAULT_VIDEOS_PATH, CHECK_INTERVAL


class VideoLooper:
    def __init__(self, videos_path=None):
        self.videos_path = Path(videos_path or DEFAULT_VIDEOS_PATH)
        self.running = True
        self.setup_logging()

        self.time_sync = TimeSyncManager()
        self.projector = ProjectorController()
        self.hdmi = HDMIController()
        self.player = Player(self.hdmi, self.projector)
        self.usb_sync = USBSync(str(self.videos_path))

        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def setup_logging(self):
        """Setup logging configuration - minimal logging to reduce SD card wear"""
        logging.basicConfig(
            level=logging.WARNING,  # Warnings and errors only
            format='%(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stderr)  # No file writes to reduce SD card wear
            ]
        )
        self.logger = logging.getLogger(__name__)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.running = False
        self.player.stop_video(standby_hdmi=True)
        self.projector.disconnect()
        sys.exit(0)

    def run(self):
        """Main loop"""
        try:
            self.usb_sync.sync_on_boot()
        except Exception as e:
            self.logger.error(f"USB sync failed: {e}")
        
        # Load the system time from the RTC
        self.time_sync.sync_time()
        
        current_folder = None
        time_entry_held = False
        while self.running:
            try:
                # Boot menu is setting the time: keep the screen free and awake for it,
                # then re-check the schedule against the new time as soon as it's done
                if time_entry.is_active():
                    if not time_entry_held:
                        time_entry_held = True
                        self.player.stop_video(standby_hdmi=False)
                        current_folder = None
                        if self.hdmi.is_available():
                            self.hdmi.wake_hdmi()
                    time_entry.process_request(self.time_sync.set_time_manually)
                    time.sleep(0.5)
                    continue
                time_entry_held = False

                active_folder_info = scheduler.find_active_folder(self.videos_path)
                
                if active_folder_info:
                    folder_path, video_files = active_folder_info
                    if current_folder != folder_path or not self.player.is_playing():
                        # Folder changed, or VLC isn't running: (re)start the video
                        self.player.stop_video(standby_hdmi=False)
                        started = self.player.start_video(video_files, folder_path)
                        current_folder = folder_path if started else None
                    elif self.hdmi.is_available():
                        # Video is playing correctly. This only sends a command if
                        # the last attempt to wake the display failed.
                        self.hdmi.wake_hdmi()
                else:
                    # No active folder - stop video and put HDMI in standby
                    if self.player.current_folder is not None or self.player.is_playing():
                        # Video is playing but folder is no longer active - stop it
                        self.player.stop_video(standby_hdmi=True)
                        current_folder = None
                    elif self.hdmi.is_available():
                        # Nothing to play. This only sends a command if the display
                        # was last told to be on, or the last attempt failed.
                        self.hdmi.standby_hdmi()

                # Wait for the next check, but react to time entry within a second
                for _ in range(CHECK_INTERVAL):
                    if time_entry.is_active():
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)
        
        self.player.stop_video(standby_hdmi=True)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Video Looper')
    parser.add_argument('--videos-path', default=None,
                       help='Path to videos directory (default: /home/looper/videos)')
    parser.add_argument('--test', action='store_true',
                       help='Test mode - show what would be played without starting VLC')
    parser.add_argument('--time-status', action='store_true',
                       help='Show time synchronization status')
    parser.add_argument('--sync-time', action='store_true',
                       help='Force time synchronization')
    parser.add_argument('--projector-test', action='store_true',
                       help='Test projector connection')
    parser.add_argument('--projector-start', action='store_true',
                       help='Start projector')
    parser.add_argument('--projector-stop', action='store_true',
                       help='Stop projector')
    parser.add_argument('--list-ports', action='store_true',
                       help='List available serial ports')
    parser.add_argument('--usb-sync', action='store_true',
                       help='Sync videos from USB drive')
    parser.add_argument('--usb-sync-test', action='store_true',
                       help='Test USB sync (show what would be synced without copying)')
    parser.add_argument('--usb-path', default=None,
                       help='Path to USB drive to sync from (optional, auto-detects if not specified)')
    parser.add_argument('--display-folder-info', action='store_true',
                       help='Display folder information on screen for 20 seconds')
    
    args = parser.parse_args()
    
    looper = VideoLooper(args.videos_path)
    
    if args.test:
        # Test mode - just show what would be active
        active_folder_info = scheduler.find_active_folder(looper.videos_path)
        if active_folder_info:
            folder_path, video_files = active_folder_info
            print(f"Active folder: {folder_path.name}")
            print(f"Video files: {[f.name for f in video_files]}")
        else:
            print("No active folders found")
        return
    
    elif args.time_status:
        # Show time synchronization status
        status = looper.time_sync.get_time_status()
        print("Time Synchronization Status:")
        for key, value in status.items():
            print(f"  {key}: {value}")
        return
    
    elif args.sync_time:
        # Force time synchronization
        print("Forcing time synchronization...")
        if looper.time_sync.sync_time():
            print("✓ Time synchronization successful")
        else:
            print("✗ Time synchronization failed")
        return
    
    elif args.projector_test:
        # Test projector connection
        print("Testing projector connection...")
        if looper.projector.test_connection():
            print("✓ Projector connection test successful")
        else:
            print("✗ Projector connection test failed")
        return
    
    elif args.projector_start:
        # Start projector
        print("Starting projector...")
        if looper.projector.connect():
            if looper.projector.start_projector():
                print("✓ Projector started successfully")
            else:
                print("✗ Failed to start projector")
            looper.projector.disconnect()
        else:
            print("✗ Failed to connect to projector")
        return
    
    elif args.projector_stop:
        # Stop projector
        print("Stopping projector...")
        if looper.projector.connect():
            if looper.projector.stop_projector():
                print("✓ Projector stopped successfully")
            else:
                print("✗ Failed to stop projector")
            looper.projector.disconnect()
        else:
            print("✗ Failed to connect to projector")
        return
    
    elif args.list_ports:
        # List available serial ports
        print("Available serial ports:")
        ports = looper.projector.get_available_ports()
        for port in ports:
            print(f"  {port['device']}: {port['description']} ({port['manufacturer']})")
        return
    
    elif args.usb_sync_test:
        # Test USB sync (scanning only, no copying)
        print("Testing USB sync (scanning only, no copying)...")
        print(f"\nScanning USB drives...")
        usb_mounts = looper.usb_sync.find_usb_drives()
        print(f"Found {len(usb_mounts)} potential USB drive(s):")

        for mount in usb_mounts:
            print(f"  - {mount}")
            valid_folders = looper.usb_sync.get_valid_folders(mount)
            print(f"    Valid video folders: {len(valid_folders)}")
            for folder_name in valid_folders.keys():
                print(f"      - {folder_name}")

        print(f"\nLocal video folders in {looper.videos_path}:")
        local_folders = looper.usb_sync.get_valid_folders(looper.videos_path)
        print(f"  Found {len(local_folders)} valid folder(s):")
        for folder_name in local_folders.keys():
            print(f"    - {folder_name}")

        source = looper.usb_sync.find_sync_source(usb_mounts)
        if source:
            plan = looper.usb_sync.plan_sync(source)
            print(f"\nIf synced from {source}, would:")
            for old_name, new_name in plan['rename']:
                print(f"  - Rename folder: {old_name} -> {new_name}")
            for folder_name in plan['copy']:
                print(f"  - Copy folder: {folder_name}")
            for folder_name in plan['update']:
                print(f"  - Update folder: {folder_name}")
            for folder_name in plan['delete']:
                print(f"  - Delete folder: {folder_name}")
        return

    elif args.usb_sync:
        # Manual USB sync
        print("Syncing from USB drive...")
        try:
            if args.usb_path:
                print(f"Using USB path: {args.usb_path}")
                success = looper.usb_sync.sync_usb_to_local(Path(args.usb_path))
                if success:
                    print("✓ USB sync completed successfully")
                else:
                    print("✗ USB sync completed with errors (check logs)")
            else:
                success = looper.usb_sync.sync_on_boot()
                if success:
                    print("✓ USB sync completed successfully")
                else:
                    print("✗ No USB drives with valid video folders found")
        except Exception as e:
            print(f"✗ USB sync failed: {e}")
        return
    
    elif args.display_folder_info:
        # Display folder information on screen and show boot menu
        menu = BootMenu(looper.videos_path, looper.player)
        menu_result = menu.display_folder_info_on_screen()
        
        # Check if demo mode was selected
        if menu_result == 'demo':
            menu.run_demo_mode()
        return
    
    looper.run()


if __name__ == '__main__':
    main()
