# Raspberry Pi 5 Video Looper Documentation

## Overview

This project creates an automated video looper system for Raspberry Pi 5 that uses VLC media player without GUI. The system supports intelligent scheduling through folder naming conventions, allowing you to control when specific video sets are played based on date and time.

## Features

- **Headless VLC Operation**: Runs VLC without GUI for optimal performance
- **Date/Time Scheduling**: Control video playback through folder naming
- **Automatic Time Synchronization**: Uses NTP when internet is available, falls back to RTC
- **Projector Control**: USB-to-serial communication with projectors/beamers
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
- Raspberry Pi 5 with Raspberry Pi OS
- Internet connection for package installation and NTP synchronization
- Video files in supported formats (MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V)
- USB-to-serial adapter for projector control (optional)

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
- Update system packages
- Install VLC, Python dependencies, and time synchronization tools
- Configure NTP synchronization with multiple servers
- Create necessary directories
- Copy files to appropriate locations
- Set up the systemd service
- Configure permissions
- Test the installation
- Create example folder structure

### Manual Installation

If you prefer manual installation:

1. **Install dependencies**:
   ```bash
   sudo apt update
   sudo apt install -y vlc python3 python3-pip python3-venv git ffmpeg ntp ntpdate systemd-timesyncd python3-requests
   ```

2. **Create directories**:
   ```bash
   mkdir -p /home/pi/video_looper
   mkdir -p /home/pi/videos
   ```

3. **Copy files**:
   ```bash
   cp video_looper.py /home/pi/video_looper/
   cp time_sync.py /home/pi/video_looper/
   sudo cp video-looper.service /etc/systemd/system/
   ```

4. **Set permissions**:
   ```bash
   chmod +x /home/pi/video_looper/video_looper.py
   chmod +x /home/pi/video_looper/time_sync.py
   sudo chown -R pi:pi /home/pi/video_looper
   sudo chown -R pi:pi /home/pi/videos
   ```

5. **Configure time synchronization**:
   ```bash
   sudo systemctl enable systemd-timesyncd
   sudo systemctl start systemd-timesyncd
   ```

6. **Enable and start service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable video-looper
   sudo systemctl start video-looper
   ```

## Usage

### Adding Videos

1. **Create folders** with the naming convention in `/home/pi/videos/`
2. **Add video files** to the appropriate folders
3. **The system will automatically detect and play videos** based on the current date and time

### Example Folder Structure

```
/home/pi/videos/
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
cd /home/pi/video_looper
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

3. **Manual Sync**: Force synchronization when needed
   ```bash
   python3 video_looper.py --sync-time
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
python3 video_looper.py --videos-path /custom/videos/path --log-file /custom/log/path
```

### Service Configuration

The systemd service file (`/etc/systemd/system/video-looper.service`) can be modified to:
- Change the user/group
- Modify environment variables
- Adjust restart behavior
- Change security settings

## Troubleshooting

### Common Issues

1. **Service won't start**:
   - Check if VLC is installed: `vlc --version`
   - Verify Python script permissions: `ls -la /home/pi/video_looper/video_looper.py`
   - Check service logs: `sudo journalctl -u video-looper -n 50`

2. **No videos playing**:
   - Verify folder naming convention
   - Check if current date/time matches folder schedule
   - Ensure video files are in supported formats
   - Test with `--test` flag

3. **VLC errors**:
   - Check if display is available: `echo $DISPLAY`
   - Verify video file formats are supported
   - Check VLC installation: `sudo apt install --reinstall vlc`

4. **Time synchronization issues**:
   - Check NTP status: `timedatectl status`
   - Test time sync: `python3 time_sync.py --test`
   - Check internet connectivity: `ping -c 3 8.8.8.8`
   - Restart timesyncd: `sudo systemctl restart systemd-timesyncd`

5. **Permission issues**:
   - Ensure pi user owns directories: `sudo chown -R pi:pi /home/pi/videos`
   - Check log file permissions: `sudo chown pi:pi /var/log/video_looper.log`

6. **Projector control issues**:
   - Check serial port: `python3 video_looper.py --list-ports`
   - Test projector: `python3 video_looper.py --projector-test`
   - Verify USB-to-serial adapter: `lsusb`
   - Check projector commands in manual
   - Verify baud rate settings
   - Test with manual commands: `python3 video_looper.py --projector-start`

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
cd /home/pi/video_looper
python3 video_looper.py --videos-path /home/pi/videos
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
├── video-looper.service     # Systemd service file
├── install.sh              # Installation script
├── setup_examples.sh        # Example folder structure setup
├── troubleshoot.sh          # Troubleshooting and diagnostics
├── projector_config_examples.txt # Projector configuration examples
├── config.conf              # Configuration file
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

- The service runs as the `pi` user (not root)
- Limited file system access through systemd security settings
- Log files are accessible only to the pi user
- No network services exposed

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review service logs: `sudo journalctl -u video-looper -f`
3. Test with `--test` flag to verify configuration
4. Ensure all prerequisites are met

## License

This project is provided as-is for educational and personal use.
