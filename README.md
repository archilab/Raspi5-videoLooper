# Raspberry Pi 5 Video Looper

Unattended video playback for a Raspberry Pi 5 driving a screen or projector, for signage or installations. It works offline: you put videos in folders, and **each folder's name sets when it plays**.

- Loops videos silently and fullscreen with VLC, starting on boot
- Schedules by date and daily hours, with several time windows a day and overnight windows
- Updates content from a USB drive when the service starts
- Keeps time with the Pi's battery-backed real-time clock (RTC), with no network needed
- Switches a projector on and off over USB serial, with no setup for known brands
- Switches the HDMI signal off outside scheduled hours, so most displays go to sleep

## Scheduling

Name a folder like this:

```
YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM
```

To play in several time windows a day, join them with `_and_`. One folder with several windows also avoids keeping the same videos in several folders.

| Folder name | Plays |
|---|---|
| `2026-12-01_to_2026-12-31_1000_to_2200` | Every day in December, 10:00 to 22:00 |
| `2026-06-15_to_2026-06-30_0800_to_2000` | June 15–30, 08:00 to 20:00 |
| `2026-12-01_to_2026-12-03_2200_to_0600` | Overnight: 22:00 on Dec 1 until 06:00 on Dec 4 |
| `2026-12-01_to_2026-12-31_0500_to_0900_and_1600_to_2300` | Every day in December, 05:00 to 09:00 and 16:00 to 23:00 |
| `2026-12-01_to_2026-12-31_0700_to_0900_and_1200_to_1400_and_1800_to_2200` | Three windows every day in December |

- **Overnight windows:** if the end time is before the start time, the window starts on each date in the range and ends the next morning. The last night therefore runs into the morning after the end date.
- **Between windows:** the video and projector stop and the HDMI signal goes off, unless another folder is active. With a projector, keep gaps longer than its cool-down, or it may ignore the next start. A window can be overnight, and windows that touch or overlap play without a restart.
- **Overlaps:** if several folders are active, the one with the latest start date plays. Give overlapping folders different start dates, since the winner is otherwise arbitrary.
- **Videos:** every video in the folder loops in filename order. Supported: `.mp4 .avi .mov .mkv .wmv .flv .webm .m4v`.
- **Ignored:** folders with no videos or a name that doesn't match, and files starting with `.`. The whole name must match, so one bad window or extra text makes a folder invalid. It won't play, and USB sync neither copies nor removes it. If it starts like a schedule, a warning is logged.
- **Timing:** the schedule is checked every 30 seconds, so changes take up to 30 seconds to apply. You can add folders without restarting.

```
/home/looper/videos/
├── 2026-12-01_to_2026-12-31_1000_to_2200/
│   ├── christmas.mp4
│   ├── sale.mp4
│   └── projector.txt          (optional, see Projector control)
└── 2026-06-15_to_2026-06-30_0800_to_2000/
    └── summer.mp4
```

## Installation

You need a Raspberry Pi 5 running Raspberry Pi OS Lite, an internet connection during installation, and a user with `sudo`. Don't run the script as root.

```bash
chmod +x install.sh
./install.sh
```

The script changes the whole system, so read it first on a Pi that has other uses. It:

- Upgrades all packages, and installs VLC, `python3-serial` and others
- Creates the `looper` user, which runs everything, and sets it to log in automatically on the HDMI console
- If `looper` already exists and `admin` doesn't, creates `admin` with **passwordless sudo**
- **Disables NTP**, because the system runs on the RTC alone
- Sets up USB automounting at `/media/usb1` to `/media/usb4`
- Installs and starts the `video-looper` and `rtc-time-restore` services
- Creates example folders dated 2024, containing empty placeholder videos, which you can delete

`setup_examples.sh` creates more example folders, and `troubleshoot.sh` runs a read-only system check.

## Updating videos from a USB drive

Put your schedule folders in the top level of the drive, plug it in, and restart the service or reboot. The sync only runs when the service starts.

**The USB drive is the source of truth.** Local folders that aren't on the drive are removed, so the drive must hold everything you want to keep playing. A drive with no valid folders changes nothing.

To see what a sync would do, without changing anything:

```bash
sudo -u looper python3 /home/looper/video_looper/video_looper.py --usb-sync-test
```

- **Same name:** new and changed files are copied, and videos and projector settings no longer on the drive are removed from that folder. Other files are left alone.
- **New name, same video filenames:** if a local folder that's leaving has the same video filenames, it's renamed instead of copied, so changing a schedule is quick.
- **Several drives:** the first one with valid folders is used.
- **Interruptions:** each file is copied to a hidden temporary name and then renamed, so an interrupted copy can't damage an existing video.
- **Errors:** if a copy fails, for example on a full disk, nothing old is deleted. The screen shows a summary and the details go to the log.

## Boot menu

After each boot, the HDMI console shows the folder list for 10 seconds, then this menu for 20 seconds. Connect a USB keyboard to use it. The menu only appears at boot, so reboot to reach it again.

| Key | Action |
|---|---|
| `1` | Demo mode: plays each folder for one minute with 30 seconds between, ignoring schedules |
| `2` | Set the date and time |
| `Enter` | Continue, which also happens when the countdown ends |

The service's video can start while the menu is on screen and cover it. Pressing `1` or `2` still works: the video stops within a couple of seconds, and returns by itself when you're done.

The HDMI signal stays on for this menu even when nothing is scheduled. A projector doesn't switch on for it, though, so if a projector is your only screen, switch it on with its own remote first.

## Time

The system uses only the RTC, with NTP disabled. The time is loaded from the RTC at startup, so **schedules are only as accurate as the RTC**.

**To set the time**, press `2` at the boot menu and enter the year, month, day, hour and minute. A value with fewer digits than the prompt's maximum, like `5` for May, needs `Enter`. Seconds are set to `00`. The video waits until you finish or cancel, and the service then rechecks the schedule. Each step cancels itself after 60 seconds.

**RTC battery:** without a working battery, the RTC stops while the Pi has no power and comes back wrong. If you use the official rechargeable Raspberry Pi RTC battery, enable charging in `/boot/firmware/config.txt` and reboot:

```
dtparam=rtc_bbat_vchg=3000000
```

Never enable this with a non-rechargeable cell such as a CR2032.

## Display control

The service switches the HDMI signal on before playing and off when nothing is scheduled. It does this through the kernel's framebuffer blanking, without needing any support from the display. **What the display does with no signal is up to the display:** most go to sleep, some show a "no signal" message, and some projectors have their own settings for it.

- **After starting:** the signal stays on for the first 60 seconds after the service starts, so the boot menu is visible even when nothing is scheduled. To reach the menu after the signal is off, reboot.
- **When the service stops:** the signal is switched back on, so the console can be used.
- **While the signal is off:** keyboard input doesn't bring it back, and neither does turning the display on by hand. Restarting the service brings it back for 60 seconds, and stopping the service brings it back until the service starts again:

```bash
sudo systemctl stop video-looper
```

To check the signal state from another machine, read this file, which shows `On` or `Off`:

```bash
cat /sys/class/drm/card1-HDMI-A-1/dpms
```

## Projector control

Connect a projector through a USB-to-serial adapter. **With no settings file in a video folder, the known brands' commands are sent automatically:**

| | Commands, in order |
|---|---|
| Start | `~0000 1`, then `PWR ON` |
| Stop | `~0000 0`, then `PWR OFF` |

- **Timing:** it waits 2 seconds, sends the start commands with 1 second between them, then waits 5 seconds before the video starts. Stopping waits 1 second first.
- **Serial port:** the first `/dev/ttyUSB*` or `/dev/ttyACM*` at 9600 baud. With no adapter, the video just plays, and an adapter plugged in later is found the next time a video starts.
- **When it switches:** it starts when a video starts, and stops when nothing is scheduled or the service stops. It stays on through a VLC restart, a change to a folder with the same settings, time entry and demo mode, because many projectors ignore a start command while cooling down. Restarting the service, including through `deploy.sh`, does switch it off and on again, and a gap between time windows switches it off.
- **Other serial devices:** every adapter is treated as a projector connection, so a different device on the first port receives these commands too. To turn this off for a folder, add a settings file with `enable_projector=false`.

To add a brand, add its commands to `BRAND_START_COMMANDS` and `BRAND_STOP_COMMANDS` in `constants.py`.

### Settings for a folder

A settings file in a video folder replaces the automatic commands and their delays, and it needs `enable_projector=true` to control anything. It can be named `projector.txt`, `projector.conf` or `config.txt`, as `key=value` lines or JSON. See `projector_config_examples.txt` for full examples.

```
enable_projector=true
serial_port=/dev/ttyUSB0
baud_rate=9600
start_command=PWR ON
stop_command=PWR OFF
start_delay=2
stop_delay=1
video_start_delay=5
```

| Setting | Meaning | Default |
|---|---|---|
| `enable_projector` | Control the projector for this folder. Needed in a settings file | `false` |
| `serial_port` | Adapter port; find it with `--list-ports` | `/dev/ttyUSB0` |
| `baud_rate` | Serial speed from the projector's manual | `9600` |
| `timeout` | Serial timeout in seconds | `5` |
| `start_command`, `stop_command` | Power commands; a carriage return is added | `~0000 1`, `~0000 0` (Optoma) |
| `start_delay`, `stop_delay` | Seconds to wait before sending each command | `0` |
| `video_start_delay` | Seconds between the start command and the video | `0` |
| `wait_for_response` | Read the reply after sending, without checking it | `false` |
| `configure_stty` | Also set up the port with `stty` | `true` |

**Commands differ by model, so check your projector's manual.** The system only sends commands. It doesn't check that the projector responded, and a failure doesn't stop the video.

### Testing

These use the settings of the folder playing now, otherwise the first folder with settings, otherwise the automatic commands if there's an adapter.

```bash
sudo -u looper python3 /home/looper/video_looper/video_looper.py --projector-test
```

`--projector-test` only opens the serial port and sends nothing. That shows the adapter and settings work, but not that a projector is listening. `--projector-start` and `--projector-stop` send the real commands, and need projector control to be enabled.

## Commands

Run these as `looper`, for example `sudo -u looper python3 /home/looper/video_looper/video_looper.py --test`.

| Option | Action |
|---|---|
| `--test` | Show what should be playing now |
| `--videos-path PATH` | Use another videos folder, combined with another option |
| `--time-status` | Show the time sync mode |
| `--sync-time` | Load the system time from the RTC |
| `--list-ports` | List serial ports |
| `--projector-test` | Check that the projector's serial port opens |
| `--projector-start` | Send the power on command, or commands |
| `--projector-stop` | Send the power off command, or commands |
| `--usb-sync-test` | Preview a USB sync |
| `--usb-sync` | Sync now, and `--usb-path PATH` picks the drive. Stop the service first, since the sync can replace or remove what's playing |
| `--display-folder-info` | Show the folder list and boot menu |

Managing the service:

```bash
sudo systemctl status video-looper
sudo systemctl restart video-looper
sudo journalctl -u video-looper -f
```

## Troubleshooting

`troubleshoot.sh` checks most of this automatically.

| Problem | What to check |
|---|---|
| Nothing plays | Run `--test`. Check the folder name, that it contains a video, and that the Pi's `date` is correct |
| Wrong time after power loss | The RTC battery, under Time above |
| New folders didn't arrive | The sync only runs at service start. Check with `--usb-sync-test` and `mount \| grep media` |
| Local folder disappeared | It wasn't on the USB drive when the service started |
| Display stays on after hours | Check whether the signal is really `Off`, under Display control above. If it is, check the display's no-signal or power-saving settings |
| Screen is dark when it should show something | The signal is off because nothing is scheduled. Run `--test` and see Display control above |
| Projector does nothing | Run `--list-ports` and `--projector-test`, then check the commands and baud rate against the manual. A settings file replaces the automatic commands |
| Projector stays off after a short gap or restart | It may have ignored the start while cooling down. Use longer gaps between time windows |
| Service won't start | `sudo journalctl -u video-looper -n 50` |

Only warnings and errors are logged, to the system journal and not to a file, to reduce SD card wear. Errors from the boot menu aren't logged, because the login script discards them. The journal may not survive a reboot, depending on the system's configuration.

## How it works

Two systemd services run as `looper`, with permission to set the clock. `rtc-time-restore` sets the clock early in boot. `video-looper` then waits for the display driver, gives `looper` write access to the kernel's HDMI blank file, which is its only step running as root, then syncs from USB and runs the main loop.

The boot menu is a separate process started by the console login. When it needs the screen, it takes a file lock. The service then stops its video and keeps the HDMI signal and projector on until the lock is released, which the kernel does even if the menu crashes. The menu has no permission to set the clock, so it passes the entered time to the service.

| File | Responsibility |
|---|---|
| `video_looper.py` | Main loop and command line |
| `scheduler.py` | Parses folder names, including time windows, and decides what should play |
| `player.py` | VLC, and the display and projector around playback |
| `boot_menu.py` | Menu screens, key input, time prompts, demo mode |
| `time_entry.py` | The hold and time handoff between menu and service |
| `time_sync.py` | Reads and writes the RTC and system clock |
| `usb_sync.py` | USB detection, sync planning and safe copying |
| `hdmi_controller.py` | Switches the HDMI signal on and off |
| `projector_controller.py` | Finds the USB serial adapter, and sends projector commands |
| `console.py` | Writes to the HDMI console |
| `constants.py` | Shared settings, like paths, the check interval and the known projector brands |
| `video-looper.service`, `rtc-time-restore.service` | The two systemd services |
| `99-looper-rtc.rules` | Gives `looper` access to the RTC device |
| `install.sh`, `deploy.sh` | Set up a Pi, and update its code |

## Development

Tests use only Python's standard library plus `pyserial`, and run on any Mac or Linux machine. They never touch the real clock, display, projector or VLC.

```bash
python3 -m unittest
```

`deploy.sh` updates the code on a Pi that `install.sh` has already set up, using SSH key login and passwordless `sudo`. It only restarts the service if something changed, which interrupts the video and switches a connected projector off and on, and it refuses to restart if the USB sync would delete local folders. It doesn't change the videos folder itself, and new modules need adding to the file lists in both `deploy.sh` and `install.sh`, which the tests check.

```bash
LOOPER_HOST=admin@192.168.1.140 ./deploy.sh --check
LOOPER_HOST=admin@192.168.1.140 ./deploy.sh
```

Other options are `--restart` to force a restart, and `--allow-usb-delete` to override the USB check.

## Security notes

- The services run as `looper` and need no network. They hold the capability to set the clock. `video-looper` has one short step that runs as root at startup, to give `looper` write access to the HDMI blank file.
- `install.sh` gives `hwclock` that capability too, and the RTC rule gives `looper` the device, so the `looper` user can change the clock outside the services.
- The HDMI console logs in as `looper` automatically, so anyone with a keyboard on the Pi gets that user's shell.
- `admin`, when `install.sh` creates it, has passwordless `sudo`, so protect its SSH access.
- Every USB serial adapter receives the projector commands unless a folder's settings say otherwise, so don't connect other serial devices without checking.

## License

Provided as-is for educational and personal use.
