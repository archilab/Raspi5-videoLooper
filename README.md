# Raspberry Pi 5 Video Looper Documentation

## Overview

This project creates an automated video looper system for Raspberry Pi 5 that uses VLC media player without GUI. The system supports intelligent scheduling through folder naming conventions, allowing you to control when specific video sets are played based on date and time.

## Features

- **Headless VLC Operation**: Runs cvlc (command-line VLC) as unprivileged user without GUI for optimal performance
- **Date/Time Scheduling**: Control video playback through folder naming
- **Automatic Time Synchronization**: Uses NTP when internet is available, falls back to RTC
- **Projector Control**: USB-to-serial communication with projectors/beamers
- **HDMI Display Control**: Automatic HDMI standby/wake using CEC (Consumer Electronics Control)
- **Display Clearing**: Automatically clears display when video stops
- **USB Drive Sync**: Automatic synchronization of video folders from USB drives on boot
- **Smart Folder Renaming**: Automatically renames existing folders when USB folder has same video files
- **Configurable Delays**: Video start delays and projector timing control
- **Automatic Startup**: Runs as a systemd service, starting automatically on boot
- **Multiple Video Support**: Loops through all videos in active folders
- **Graceful Switching**: Automatically switches between different video sets based on schedule
- **Comprehensive Logging**: Detailed logs for monitoring and debugging
- **Easy Management**: Simple service commands for start/stop/restart

## Folder Naming Convention

The system uses a specific folder naming convention to control when videos are played:

```
YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM
```

### Examples:
- `2024-01-01_to_2024-01-31_0900_to_1800` - Play videos from January 1-31, 2024, between 9:00 AM and 6:00 PM
- `2024-12-01_to_2024-12-31_1000_to_2200` - Play videos from December 1-31, 2024, between 10:00 AM and 10:00 PM
- `2024-06-15_to_2024-06-30_0800_to_2000` - Play videos from June 15-30, 2024, between 8:00 AM and 8:00 PM

### Format Details:
- **Start Date**: `YYYY-MM-DD` format (e.g., `2024-01-01`)
- **End Date**: `YYYY-MM-DD` format (e.g., `2024-01-31`)
- **Start Time**: `HHMM` format in 24-hour time (e.g., `0900` for 9:00 AM)
- **End Time**: `HHMM` format in 24-hour time (e.g., `1800` for 6:00 PM)

## Installation

### Prerequisites
- Raspberry Pi 5 with Raspberry Pi OS (lite)
- Internet connection for package installation and NTP synchronization
- The installation script will automatically create the "looper" user if it doesn't exist
- Video files in supported formats (MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V)
- USB-to-serial adapter for projector control (optional)
- HDMI display with CEC support (optional, for automatic display control)
- USB drive with valid video folders (optional, for automatic sync)

### Quick Installation

1. **Download the project files** to your Raspberry Pi
2. **Make the installation script executable**:
   ```bash
   chmod +x install.sh
   ```
3. **Run the installation script**:
   ```bash
   ./install.sh
   ```

The installation script will:
- Create the "looper" user (if it doesn't exist)
- Update system packages
- Install VLC, Python dependencies, time synchronization tools, and CEC utilities
- Configure NTP synchronization with multiple servers
- Create necessary directories (`/home/looper/video_looper` and `/home/looper/videos`)
- Copy files to appropriate locations (including HDMI controller and USB sync modules)
- Set up the systemd service
- Configure permissions
- Test the installation
- Create example folder structure

### Manual Installation

If you prefer manual installation:

1. **Install dependencies**:
   ```bash
   sudo apt update
   sudo apt install -y vlc python3 python3-pip git ffmpeg python3-requests python3-serial cec-utils
   ```

2. **Create looper user** (if it doesn't exist):
   ```bash
   sudo useradd -m -s /bin/bash looper
   ```

3. **Create directories**:
   ```bash
   sudo mkdir -p /home/looper/video_looper
   sudo mkdir -p /home/looper/videos
   ```

4. **Copy files**:
   ```bash
   sudo cp video_looper.py /home/looper/video_looper/
   sudo cp time_sync.py /home/looper/video_looper/
   sudo cp projector_controller.py /home/looper/video_looper/
   sudo cp hdmi_controller.py /home/looper/video_looper/
   sudo cp console.py constants.py boot_menu.py player.py scheduler.py time_entry.py /home/looper/video_looper/
   sudo cp usb_sync.py /home/looper/video_looper/
   sudo cp video-looper.service /etc/systemd/system/
   ```

5. **Set permissions**:
   ```bash
   sudo chmod +x /home/looper/video_looper/video_looper.py
   sudo chmod +x /home/looper/video_looper/time_sync.py
   sudo chmod +x /home/looper/video_looper/projector_controller.py
   sudo chmod +x /home/looper/video_looper/hdmi_controller.py
   sudo chmod +x /home/looper/video_looper/usb_sync.py
   sudo chown -R looper:looper /home/looper/video_looper
   sudo chown -R looper:looper /home/looper/videos
   ```

6. **Configure time synchronization**:
   ```bash
   sudo systemctl enable systemd-timesyncd
   sudo systemctl start systemd-timesyncd
   ```

7. **Enable and start service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable video-looper
   sudo systemctl start video-looper
   ```

## Usage

### Adding Videos

1. **Create folders** with the naming convention in `/home/looper/videos/`
2. **Add video files** to the appropriate folders
3. **The system will automatically detect and play videos** based on the current date and time

### Example Folder Structure

```
/home/looper/videos/
├── 2024-01-01_to_2024-01-31_0900_to_1800/
│   ├── morning_ad.mp4
│   ├── product_demo.mp4
│   └── company_intro.mp4
├── 2024-02-01_to_2024-02-29_0800_to_2000/
│   ├── valentine_promo.mp4
│   └── february_sale.mp4
└── 2024-12-01_to_2024-12-31_1000_to_2200/
    ├── christmas_ad.mp4
    ├── holiday_sale.mp4
    └── new_year_promo.mp4
```

### Service Management

**Start the service**:
```bash
sudo systemctl start video-looper
```

**Stop the service**:
```bash
sudo systemctl stop video-looper
```

**Restart the service**:
```bash
sudo systemctl restart video-looper
```

**Check service status**:
```bash
sudo systemctl status video-looper
```

**View logs**:
```bash
sudo journalctl -u video-looper -f
```

**Disable autostart**:
```bash
sudo systemctl disable video-looper
```

### Testing

**Test mode** (shows what would be played without starting VLC):
```bash
cd /home/looper/video_looper
python3 video_looper.py --test
```

**Test with custom videos path**:
```bash
python3 video_looper.py --videos-path /path/to/videos --test
```

**Check time synchronization status**:
```bash
python3 video_looper.py --time-status
```

**Force time synchronization**:
```bash
python3 video_looper.py --sync-time
```

**Test USB sync** (dry-run, shows what would be synced):
```bash
python3 video_looper.py --usb-sync-test
```

**Manual USB sync**:
```bash
python3 video_looper.py --usb-sync
```

**USB sync from specific path**:
```bash
python3 video_looper.py --usb-sync --usb-path /media/looper/USBDRIVE
```

## USB Drive Synchronization

The system automatically synchronizes video folders from USB drives on boot. This allows you to update video content by simply inserting a USB drive.

### How It Works

1. **On Boot**: The system checks for mounted USB drives
2. **Valid Folders**: Only folders matching the naming convention with at least one video file are synced
3. **Smart Renaming**: If a USB folder has the same video files as an existing local folder (but different name), the local folder is renamed instead of copying files again
4. **File Sync**: Missing files are copied, existing files are updated if newer or different size
5. **Cleanup**: Local folders not found on USB (with valid folders) are deleted

### USB Sync Process

When a USB drive is detected on boot:

1. **Scan USB Drive**: System searches common mount points (`/media/looper`, `/mnt`, `/run/media/looper`)
2. **Find Valid Folders**: Identifies folders matching the naming pattern with video files
3. **Compare with Local**: Compares USB folders with `/home/looper/videos/`
4. **Rename or Copy**:
   - If local folder with same name exists → sync files
   - If local folder with same video files exists → rename local folder to match USB name
   - If no match → copy new folder from USB
5. **Delete Obsolete**: Remove local folders not on USB (if USB has valid folders)
6. **File Management**: Copy/update individual files within folders

### Example Scenarios

**Scenario 1: New Folder on USB**
- USB has: `2024-01-01_to_2024-01-31_0900_to_1800/` with `video.mp4`
- Local has: No matching folder
- Result: Folder is copied to local

**Scenario 2: Folder Rename (Same Video Files)**
- USB has: `2024-01-01_to_2024-01-31_0900_to_1800/` with `video.mp4`
- Local has: `2023-12-01_to_2023-12-31_0900_to_1800/` with `video.mp4`
- Result: Local folder is renamed to `2024-01-01_to_2024-01-31_0900_to_1800/` (no file copy needed)

**Scenario 3: Updated Files**
- USB has: `2024-01-01_to_2024-01-31_0900_to_1800/` with updated `video.mp4`
- Local has: `2024-01-01_to_2024-01-31_0900_to_1800/` with older `video.mp4`
- Result: File is updated if USB file is newer or different size

**Scenario 4: Folder Removed from USB**
- USB has: No valid folders
- Local has: `2024-01-01_to_2024-01-31_0900_to_1800/`
- Result: Nothing changes (no deletion if USB has no valid folders)

### Manual USB Sync

You can manually trigger USB sync at any time:

```bash
# Test mode (shows what would be synced without copying)
python3 video_looper.py --usb-sync-test

# Sync from auto-detected USB drives
python3 video_looper.py --usb-sync

# Sync from specific USB path
python3 video_looper.py --usb-sync --usb-path /media/looper/USBDRIVE
```

### RTC Time Setting from USB Drive

The system can set the RTC (Real Time Clock) time from a file on the USB drive. This is useful when there's no internet connection and you need to set the system time.

**How it works:**
1. On boot, the system checks USB drives for RTC time files
2. If found, the time from the file is used to set the RTC
3. This happens before video folder sync

**RTC Time File:**
- **File names** (checked in order):
  - `rtc_time.txt` (primary)
  - `time.txt`
  - `set_time.txt`
  - `rtc_time`
- **Supported formats:**
  - ISO format: `2024-01-15T14:30:00`
  - Date + Time: `2024-01-15 14:30:00`
  - Date + Time (no seconds): `2024-01-15 14:30`
  - Unix timestamp: `1705324200`

**Example time files:**

**ISO format** (`rtc_time.txt`):
```
2024-01-15T14:30:00
```

**Date + Time format** (`rtc_time.txt`):
```
2024-01-15 14:30:00
```

**Unix timestamp** (`rtc_time.txt`):
```
1705324200
```

**Notes:**
- RTC time setting requires `sudo` permissions (handled by the system)
- The time file is read from the root of the USB drive
- Only one RTC time file is processed (first found)
- Time setting happens before video folder sync
- If time setting fails, the system continues with video sync

### USB Drive Requirements

- **Automatic Mounting**: USB drives are automatically mounted when inserted:
  - Mount points: `/media/usb0`, `/media/usb1`, `/media/usb2`, `/media/usb3`
  - USB drives are automatically mounted when inserted (using usbmount if available, otherwise udev-based mounting)
  - Mount points are owned by the `looper` user for easy access
- **Supported File Systems**: 
  - vfat (FAT32)
  - ntfs
  - ext4
  - exfat
- **Valid Folders**: Must match naming convention: `YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM`
- **Video Files**: Must contain at least one video file in supported formats
- **RTC Time File**: Optional file to set system time (see above)

### Notes

- **Manual USB Mounting Required**: USB drives must be manually mounted before syncing. The system will check common mount points for mounted USB drives.
- USB sync runs automatically on boot (waits 2 seconds for USB detection)
- RTC time file is checked first, before video folder sync
- Only valid video folders are considered for sync
- Folder renaming preserves existing video files when folder names change
- Projector config files are also synced if present
- Logs show detailed sync operations and any errors

## RTC Time Setting

The system can set the RTC (Real Time Clock) time from a file on USB drives. This is particularly useful when there's no internet connection and NTP synchronization is unavailable.

### Features

- **USB Drive Time File**: Automatically detects and reads time from USB drive
- **Multiple Formats**: Supports ISO format, date+time, and Unix timestamps
- **Automatic Setting**: Sets RTC time during USB sync on boot
- **Fallback Support**: Works when NTP is unavailable

### Time File Format

Create a file named `rtc_time.txt` (or `time.txt`, `set_time.txt`, `rtc_time`) on your USB drive root with one of these formats:

**ISO Format** (recommended):
```
2024-01-15T14:30:00
```

**Date + Time Format**:
```
2024-01-15 14:30:00
```

**Date + Time (no seconds)**:
```
2024-01-15 14:30
```

**Unix Timestamp**:
```
1705324200
```

### How It Works

1. **On Boot**: System checks USB drives for RTC time files
2. **File Detection**: Looks for `rtc_time.txt`, `time.txt`, `set_time.txt`, or `rtc_time` in USB root
3. **Time Parsing**: Parses time from file using supported formats
4. **RTC Setting**: Sets system time and syncs to RTC hardware clock
5. **Before Sync**: RTC time is set before video folder sync begins

### Manual RTC Time Setting

You can also set RTC time manually using the time sync module:

```bash
# Set RTC from a time file
python3 time_sync.py --set-rtc-from-file /path/to/rtc_time.txt

# Check current RTC status
python3 time_sync.py --status
```

### Example Usage

1. **Create time file on USB drive**:
   ```bash
   echo "2024-01-15T14:30:00" > /media/usb/rtc_time.txt
   ```

2. **Insert USB drive and boot Raspberry Pi**:
   - System will automatically detect and set RTC time
   - Check logs: `sudo journalctl -u video-looper | grep -i rtc`

3. **Verify time was set**:
   ```bash
   python3 time_sync.py --status
   ```

### Notes

- RTC time setting requires `sudo` permissions (handled automatically)
- Only the first RTC time file found is used
- If parsing fails, the system logs an error and continues
- Time setting happens before video folder sync
- Useful for offline installations or when NTP is unavailable

## HDMI Display Control

The system automatically manages HDMI display power using CEC (Consumer Electronics Control), allowing seamless control of connected displays.

### Features

- **Automatic Wake**: Display wakes up when video playback starts
- **Automatic Standby**: Display goes to standby when video stops
- **Display Clearing**: Screen is cleared to black when video stops
- **CEC Compatibility**: Works with any CEC-compatible HDMI display

### How It Works

1. **On Video Start**: HDMI display is woken via CEC before VLC starts
2. **During Playback**: Display remains active
3. **On Video Stop**: Display screen is cleared, then put in standby mode
4. **Folder Switches**: Display stays on during folder transitions (no standby)

### Requirements

- **CEC Support**: HDMI display must support CEC (Consumer Electronics Control)
- **CEC Utils**: Package `cec-utils` is automatically installed during setup
- **HDMI Connection**: Display must be connected via HDMI

### Manual Control

You can manually control the HDMI display:

```bash
# Wake display
python3 hdmi_controller.py --on

# Put display in standby
python3 hdmi_controller.py --off

# Check display status
python3 hdmi_controller.py --status
```

### Display Clearing

When video playback stops, the system automatically clears the display using multiple methods:
1. `fbset -blank` (primary method)
2. `setterm` console blanking
3. Direct framebuffer clearing (if accessible)
4. Terminal clear command (fallback)

This ensures no leftover video frames remain visible when playback stops.

## Configuration

### Time Synchronization

The system automatically handles time synchronization using a multi-tier approach:

1. **NTP (Network Time Protocol)**: Primary time source when internet is available
   - Uses multiple NTP servers: `pool.ntp.org`, `time.google.com`, `time.cloudflare.com`
   - Falls back to `time.nist.gov` if primary servers fail
   - Synchronizes every hour automatically

2. **RTC (Real Time Clock)**: Fallback when internet is unavailable
   - Uses the Raspberry Pi's hardware clock
   - Maintains time accuracy during offline periods
   - Can be set from USB drive time file (see RTC Time Setting section)

3. **USB Drive Time File**: Sets RTC time from file on USB drive
   - Automatically detected during USB sync on boot
   - Useful when NTP is unavailable
   - Supports multiple time formats (ISO, date+time, Unix timestamp)

4. **Manual Sync**: Force synchronization when needed
   ```bash
   python3 video_looper.py --sync-time
   ```

5. **Manual RTC Setting**: Set RTC from time file
   ```bash
   python3 time_sync.py --set-rtc-from-file /path/to/rtc_time.txt
   ```

## Projector Control

The system supports automatic projector control through USB-to-serial communication. Each video folder can have its own projector configuration.

### Configuration Files

Place a configuration file in your video folder with one of these names:
- `projector.txt` (simple format)
- `projector.conf` (JSON format)
- `config.txt` (alternative name)

### Configuration Options

```bash
# Enable/disable projector control
enable_projector=true

# Serial communication settings
serial_port=/dev/ttyUSB0
baud_rate=9600
timeout=5

# Projector commands (adjust for your projector model)
start_command=PWR ON
stop_command=PWR OFF

# Timing settings (in seconds)
start_delay=2          # Delay before sending start command
stop_delay=1           # Delay before sending stop command
video_start_delay=5    # Delay before starting video playback

# Optional settings
wait_for_response=false
```

### Example Configuration

**Simple format (`projector.txt`)**:
```
enable_projector=true
serial_port=/dev/ttyUSB0
baud_rate=9600
start_command=PWR ON
stop_command=PWR OFF
start_delay=2
video_start_delay=5
```

**JSON format (`projector.conf`)**:
```json
{
    "enable_projector": true,
    "serial_port": "/dev/ttyUSB0",
    "baud_rate": 9600,
    "start_command": "PWR ON",
    "stop_command": "PWR OFF",
    "start_delay": 2,
    "video_start_delay": 5
}
```

### Projector Commands by Brand

| Brand | Start Command | Stop Command | Notes |
|-------|---------------|--------------|-------|
| Epson | `PWR ON` | `PWR OFF` | Most common |
| Sony | `PWR ON` | `PWR OFF` | Standard RS-232 |
| Panasonic | `PWR ON` | `PWR OFF` | Standard RS-232 |
| BenQ | `PWR ON` | `PWR OFF` | Standard RS-232 |
| Optoma | `PWR ON` | `PWR OFF` | Standard RS-232 |

### Projector Management Commands

**List available serial ports**:
```bash
python3 video_looper.py --list-ports
```

**Test projector connection**:
```bash
python3 video_looper.py --projector-test
```

**Start projector manually**:
```bash
python3 video_looper.py --projector-start
```

**Stop projector manually**:
```bash
python3 video_looper.py --projector-stop
```

### Customizing Paths

You can customize the videos directory and log file location:

```bash
python3 video_looper.py --videos-path /custom/videos/path
```

### Service Configuration

The systemd service file (`/etc/systemd/system/video-looper.service`) runs as the `looper` user. The service file can be modified to:
- Modify environment variables
- Adjust restart behavior
- Change security settings

**Note**: The service is configured to run as the `looper` user. If you need to change this, you must also update the service file and ensure the user exists.

## Troubleshooting

### Common Issues

1. **Service won't start**:
   - Check if VLC is installed: `vlc --version`
   - Verify Python script permissions: `ls -la /home/looper/video_looper/video_looper.py`
   - Check service logs: `sudo journalctl -u video-looper -n 50`
   - Verify looper user exists: `id looper`

2. **No videos playing**:
   - Verify folder naming convention
   - Check if current date/time matches folder schedule
   - Ensure video files are in supported formats
   - Test with `--test` flag

3. **VLC errors**:
   - Check if display is available: `echo $DISPLAY`
   - Verify video file formats are supported
   - Check VLC installation: `sudo apt install --reinstall vlc`
   - Test cvlc directly: `cvlc --intf dummy --help`
   - Verify service is running as looper user: `ps aux | grep python3 | grep looper`

4. **Time synchronization issues**:
   - Check NTP status: `timedatectl status`
   - Test time sync: `python3 time_sync.py --test`
   - Check internet connectivity: `ping -c 3 8.8.8.8`
   - Restart timesyncd: `sudo systemctl restart systemd-timesyncd`

5. **Permission issues**:
   - Ensure looper user owns directories: `sudo chown -R looper:looper /home/looper/videos`
   - Verify looper user exists: `id looper`

6. **Projector control issues**:
   - Check serial port: `python3 video_looper.py --list-ports`
   - Test projector: `python3 video_looper.py --projector-test`
   - Verify USB-to-serial adapter: `lsusb`
   - Check projector commands in manual
   - Verify baud rate settings
   - Test with manual commands: `python3 video_looper.py --projector-start`

7. **HDMI display control issues**:
   - Verify CEC utilities installed: `which cec-client`
   - Check CEC support: `cec-client -l`
   - Test HDMI control: `python3 hdmi_controller.py --on`
   - Verify HDMI connection is active
   - Check if display supports CEC (enabled in display settings)

8. **USB sync issues**:
   - Verify USB drive is mounted: `mount | grep -i usb`
   - Check mount points: `ls -la /media/usb0 /media/usb1 /media/usb2 /media/usb3`
   - Check if usbmount is installed: `dpkg -l | grep usbmount` (optional, uses udev if not available)
   - Verify udev rules: `cat /etc/udev/rules.d/99-usb-automount.rules`
   - Check USB mount script: `ls -la /usr/local/bin/usb-mount.sh`
   - Check USB drive auto-mounting: Insert USB drive and check `/media/usb0`
   - Test USB sync: `python3 video_looper.py --usb-sync-test`
   - Verify folder naming convention matches requirements
   - Ensure folders contain at least one video file
   - Check USB drive permissions: `ls -la /media/usb0`
   - Review sync logs: `sudo journalctl -u video-looper | grep -i usb`
   - If USB drive doesn't auto-mount:
     - Check udev rules are loaded: `sudo udevadm control --reload-rules && sudo udevadm trigger`
     - Check system logs for USB events: `sudo journalctl -u systemd-udevd | grep -i usb`
     - Check dmesg for USB errors: `dmesg | grep -i usb`
     - Verify filesystem is supported (vfat, ntfs, ext4, exfat)
     - Manually test mount: `sudo mount /dev/sda1 /media/usb0`
     - Check mount script manually: `sudo /usr/local/bin/usb-mount.sh sda1`

9. **RTC time setting issues**:
   - Verify RTC time file exists on USB: `ls /media/looper/rtc_time.txt`
   - Check time file format: `cat /media/looper/rtc_time.txt`
   - Test RTC time setting: `python3 time_sync.py --set-rtc-from-file /media/looper/rtc_time.txt`
   - Verify RTC is available: `sudo hwclock --show`
   - Check for parsing errors in logs: `sudo journalctl -u video-looper | grep -i rtc`
   - Ensure time file is in root of USB drive (not in subdirectory)
   - Verify time format is supported (ISO, date+time, or Unix timestamp)
   - Check permissions: `sudo chmod 644 /media/looper/rtc_time.txt`

### Log Analysis

**View recent logs**:
```bash
sudo journalctl -u video-looper --since "1 hour ago"
```

**View all logs**:
```bash
sudo journalctl -u video-looper
```

**Follow logs in real-time**:
```bash
sudo journalctl -u video-looper -f
```

### Debug Mode

Run the script manually for debugging:
```bash
cd /home/looper/video_looper
sudo -u looper python3 video_looper.py --videos-path /home/looper/videos
```

## Advanced Usage

### Multiple Active Folders

If multiple folders are active at the same time, the system will:
1. Sort folders by start date (most recent first)
2. Play videos from the folder with the most recent start date

### Video Format Support

Supported video formats:
- MP4 (`.mp4`)
- AVI (`.avi`)
- MOV (`.mov`)
- MKV (`.mkv`)
- WMV (`.wmv`)
- FLV (`.flv`)
- WebM (`.webm`)
- M4V (`.m4v`)

### Performance Optimization

For optimal performance:
- Use MP4 format when possible (best hardware acceleration support)
- Ensure videos are properly encoded for your display resolution
- Consider using SSD storage for better performance
- Monitor CPU usage: `htop`

## File Structure

```
Raspi5-videoLooper/
├── video_looper.py          # Main Python script
├── time_sync.py             # Time synchronization module
├── projector_controller.py  # Projector control module
├── hdmi_controller.py       # HDMI display control module (CEC)
├── console.py               # Shows text on the HDMI console
├── scheduler.py             # Decides what should play from folder names
├── player.py                # VLC, display and projector around playback
├── boot_menu.py             # Boot menu, demo mode and time entry
├── time_entry.py            # Coordinates the menu and service while setting the time
├── tests/                   # Run with: python3 -m unittest
├── usb_sync.py              # USB drive synchronization module
├── video-looper.service     # Systemd service file
├── install.sh              # Installation script
├── setup_examples.sh        # Example folder structure setup
├── troubleshoot.sh          # Troubleshooting and diagnostics
├── projector_config_examples.txt # Projector configuration examples
├── README.md               # This documentation
└── .gitattributes          # Git configuration
```

## System Requirements

- **Hardware**: Raspberry Pi 5 (recommended) or Pi 4
- **OS**: Raspberry Pi OS (latest version)
- **Storage**: Minimum 8GB SD card (32GB+ recommended for videos)
- **Memory**: 4GB+ RAM recommended
- **Display**: HDMI display or monitor
- **Network**: Internet connection for installation

## Security Considerations

- The service runs as the `looper` user (not root)
- Limited file system access through systemd security settings
- Log files are accessible only to the looper user
- No network services exposed
- The looper user is automatically created during installation if it doesn't exist

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review service logs: `sudo journalctl -u video-looper -f`
3. Test with `--test` flag to verify configuration
4. Ensure all prerequisites are met

## License

This project is provided as-is for educational and personal use.
