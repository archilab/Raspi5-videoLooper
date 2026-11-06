# Raspberry Pi 5 Video Looper

Unattended video playback for a Raspberry Pi 5 driving a screen or projector, for signage or installations. It works offline, or can update itself from Nextcloud: you put videos in folders, and **each folder's name sets when it plays**.

- Loops videos fullscreen with VLC, starting on boot, silently or with sound through HDMI
- Schedules by date and daily hours, with several time windows a day and overnight windows
- Or plays videos from the top level of a USB drive in an endless loop, with no schedule to set up
- Updates content from a USB drive when the service starts, or regularly from a Nextcloud folder
- Keeps time with the Pi's battery-backed real-time clock (RTC), with optional NTP when there's internet
- Switches a projector on and off over USB serial, with no setup for known brands
- Switches the HDMI signal off outside scheduled hours, so most displays go to sleep
- Sets Wi-Fi and the time source from a menu on the screen

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
- **Timing:** the schedule is checked every 30 seconds, so changes take up to 30 seconds to apply. You can add folders without restarting, and when a playing folder's videos change, VLC restarts to pick them up.

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
- **Disables NTP**, so the system runs on the RTC alone until you switch it in the boot menu. Running the script again switches it back
- Sets up USB automounting at `/media/usb1` to `/media/usb4`
- Installs and starts the `video-looper`, `rtc-time-restore` and `video-looper-nextcloud` services. The last stays idle until Nextcloud is set up
- Creates example folders dated 2024, containing empty placeholder videos, which you can delete

`setup_examples.sh` creates more example folders, and `troubleshoot.sh` runs a read-only system check.

## Updating videos from a USB drive

Put your schedule folders in the top level of the drive, plug it in, and restart the service or reboot. The sync only runs when the service starts.

**While Nextcloud is on, USB video sync is off**, and the screen says so.

**The USB drive is the source of truth.** Local folders that aren't on the drive are removed, so the drive must hold everything you want to keep playing. A drive with no valid folders and no videos at its top level changes nothing.

### Playing videos without a schedule

Put one or more videos in the top level of a drive that has no schedule folders, and they loop endlessly in filename order. Other subfolders don't count, so `Photos` or `System Volume Information` make no difference.

| On the drive | Result |
|---|---|
| Schedule folders, with or without videos at the top level | The schedule folders are synced, and top level videos are ignored |
| Videos at the top level only | They play all the time |
| Neither | Nothing changes on the Pi |

- **This replaces the schedule folders on the Pi.** **Any drive with loose videos and no schedule folders does this**, so check first with `--usb-sync-test`. They're only removed after the videos have copied without errors, and getting them back needs a drive that holds them.
- **Where they go:** the videos are copied to `/home/looper/videos/always/`, so you can remove the drive afterwards. A drive with schedule folders replaces this folder at the next sync, or Nextcloud once it finds valid folders. The name `always` is reserved on the Pi, and a folder with that name on a drive or on Nextcloud is ignored.
- **What's copied:** only videos, `projector.txt` and `projector.conf`. Everything else at the top level stays on the drive, including `nextcloud.txt` and a generic `config.txt`.
- **If a schedule folder is also on the Pi**, for example after a failed sync, it plays during its time windows, and the looping videos play the rest of the time.
- **While this plays:** the HDMI signal and a connected projector stay on, so projector lamp hours keep adding up. The clock doesn't matter.

### What a sync does

To see what a sync would do, without changing anything:

```bash
sudo -u looper python3 /home/looper/video_looper/video_looper.py --usb-sync-test
```

- **Same name:** new and changed files are copied, and videos and projector settings no longer on the drive are removed from that folder. Other files are left alone.
- **New name, same video filenames:** if a local folder that's leaving has the same video filenames, it's renamed instead of copied, so changing a schedule is quick.
- **Several drives:** the first one with valid folders is used, otherwise the first with videos at its top level.
- **Interruptions:** each file is copied to a hidden temporary name and then renamed, so an interrupted copy can't damage an existing video.
- **Errors:** if a copy fails, for example on a full disk, nothing old is deleted. The screen shows a summary and the details go to the log.

## Updating videos from Nextcloud

Instead of a USB drive, the Pi can follow a folder on a Nextcloud server. Put your schedule folders in it, and the Pi checks every 15 minutes by default. Checks only read names, sizes and dates, so videos are only downloaded when something changed.

**Nextcloud becomes the source of truth.** Local folders that aren't on it are removed, so **deleting a folder on Nextcloud deletes it from the Pi at the next check**. USB video sync is off while this is on, because each would delete what the other added.

**Before turning this on, make sure the Nextcloud folder holds everything you want to keep playing.**

### Connecting

There are two ways to connect, and a read-only share link is the safer one, because it covers only that folder and can be revoked.

- **Share link:** in Nextcloud, share the folder by public link, with or without a password. The link must allow viewing and downloading, so a file drop link won't work, and hiding downloads may not either.
- **Account:** a username and an app password, created under Personal settings, Security. It reaches everything the account can, so use one with only the access it needs.

### Setting it up

**With the keyboard:** press `5` at the boot menu and enter the details. The Pi tests the connection and shows what it would download and remove, then asks you to confirm.

**With a USB drive:** put a file called `nextcloud.txt` in the top level of the drive, and restart the service or reboot:

```
# With a share link
share_url=https://cloud.example.com/s/abc123
password=
interval=15
```

```
# Or with an account
server=https://cloud.example.com
username=player
password=app-password-here
folder=Videos/Looper
interval=15
```

`interval` is in minutes, from 1 to 1440, and defaults to 15. The password line is optional for a share link. **Importing turns sync on without asking**, unless the file has `enabled=false`, which is a safe way to check the connection first with `--nextcloud-test`. Then turn it on with `5` in the boot menu.

Settings are only imported again if the connection details or interval in the file change. Changing only `enabled`, or removing it, does nothing to settings already imported, so turning Nextcloud off in the menu stays off.

**Remove `nextcloud.txt` from the drive afterwards**, because it contains the password. The Pi keeps its copy in `/home/looper/nextcloud.conf`, which only `looper` can read.

### What happens during a sync

- **Playback continues:** downloads run in the background at low priority. When a playing folder's videos change, VLC restarts as soon as the next schedule check sees it, within 30 seconds, which interrupts the video briefly. The projector stays on.
- **Network failures:** a failed check changes nothing, and it tries again at the next one. Interrupted downloads resume where they stopped.
- **Partial content:** a new folder stays hidden until it's complete, and files in a folder are replaced together once all have arrived.
- **Errors:** if anything fails, nothing old is removed. If there isn't enough disk space, nothing starts, and 200 MB is always left free.
- **What's downloaded:** only videos and projector settings, directly inside valid schedule folders. Folders with no valid name or no video are ignored, and if Nextcloud has no valid folders at all, nothing changes.
- **First sync:** a video with the same name and size is downloaded again if its date differs on Nextcloud.

### Checking it

The boot menu shows the state and last result. Press `5` for details, to turn it off or on, or to sync now. From a terminal:

```bash
sudo -u looper python3 /home/looper/video_looper/video_looper.py --nextcloud-status
sudo -u looper python3 /home/looper/video_looper/video_looper.py --nextcloud-test
sudo journalctl -u video-looper-nextcloud -f
```

`--nextcloud-test` connects and shows what a sync would do, without changing anything. Run these as `looper`, as shown, because other users can't read the settings and are told it isn't set up. The last result is kept in memory, so after a reboot it shows "not checked yet" until the first check, about 30 seconds after the service starts.

To turn Nextcloud off without a keyboard, delete its settings. The background service notices within seconds, and USB video sync works again the next time the main service starts. Also remove any `nextcloud.txt` from the USB drive, or it will be imported again:

```bash
sudo rm /home/looper/nextcloud.conf
```

HTTPS needs a roughly correct clock, so a badly wrong clock shows up as a connection failure. The NTP option under Time helps with this.

## Boot menu

After each boot, the HDMI console shows the folder list for 10 seconds, then this menu for 20 seconds. Connect a USB keyboard to use it. The menu only appears at boot, so reboot to reach it again.

| Key | Action |
|---|---|
| `1` | Demo mode: plays each folder for one minute with 30 seconds between, ignoring schedules |
| `2` | Set the date and time |
| `3` | Set Wi-Fi |
| `4` | Choose the time source |
| `5` | Set up Nextcloud, or see its status |
| `6` | Switch video audio on or off |
| `Enter` | Continue, which also happens when the countdown ends |

The service's video can start while the menu is on screen and cover it. Pressing a number still works: the video stops within a couple of seconds, and returns by itself when you're done.

The HDMI signal stays on for this menu even when nothing is scheduled. A projector doesn't switch on for it, though, so if a projector is your only screen, switch it on with its own remote first.

## Audio

Videos play silently by default. Press `6` at the boot menu, then `1`, to switch sound on or off. The video restarts with the new setting when you leave the menu, and the choice survives reboots. It applies to every folder and to demo mode.

- **Output:** sound goes through HDMI to the display or projector, so that device needs speakers. It uses the first HDMI port with a display connected. The Pi 5 has no headphone jack, and USB sound cards and Bluetooth aren't supported.
- **Volume:** set it on the display or projector. The Pi always sends full volume.
- **Videos with no sound track** just play silently.
- **Without a keyboard:** the setting is stored in `/home/looper/audio.conf`, as `enabled=true` or `enabled=false`, and is read each time a video starts. Anything else there counts as off.

## Wi-Fi

Press `3` at the boot menu to choose a network from a list of the nine strongest, or `0` to type the name of a hidden one, then enter its password. The password shows as stars, and Tab shows or hides it, which helps on an unfamiliar keyboard.

- **Failures:** if the connection fails, for example with a wrong password, the attempt is removed and the Pi reconnects to the previous network.
- **Remembered networks:** networks stay saved, and the most recently set one is preferred. A new network usually gives the Pi a new IP address, which the screen shows.
- **Not supported:** WEP and enterprise (802.1X) networks, and passwords that start or end with a space.
- **Passwords:** they aren't logged or passed on a command line, and NetworkManager stores them in a file only root can read.
- **Keyboard:** the characters you get depend on the Pi's keyboard layout, set in `/etc/default/keyboard`.

## Time

By default the system uses only the RTC, so **schedules are only as accurate as the RTC**. The time is loaded from the RTC at startup.

**To use NTP**, press `4` at the boot menu. The clock then follows NTP when the Pi can reach the internet, and the choice survives reboots. The RTC is updated from NTP every 10 minutes, so the time stays right after a power cut with no internet. Without internet the Pi carries on using the RTC, and NTP keeps retrying.

**To set the time by hand**, first make sure the time source is RTC only, because NTP would overwrite it. Then press `2` at the boot menu and enter the year, month, day, hour and minute. A value with fewer digits than the prompt's maximum, like `5` for May, needs `Enter`. Seconds are set to `00`. The video waits until you finish or cancel, and the service then rechecks the schedule. Each step cancels itself after 60 seconds.

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
- **When it switches:** it starts when a video starts, and stops when nothing is scheduled or the service stops. It stays on through a VLC restart, including one for updated videos, a change to a folder with the same settings, time entry and demo mode, because many projectors ignore a start command while cooling down. Restarting the service, including through `deploy.sh`, does switch it off and on again, and a gap between time windows switches it off.
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
| `--nextcloud-status` | Show the Nextcloud settings and the last check |
| `--nextcloud-test` | Connect and show what a sync would do |
| `--nextcloud-sync` | Sync from Nextcloud now |
| `--nextcloud-service` | Run the regular checks, as the background service does |
| `--usb-sync-test` | Preview a USB sync |
| `--usb-sync` | Sync now, and `--usb-path PATH` picks the drive. Stop the service first, since the sync can replace or remove what's playing. Refused while Nextcloud is on |
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
| Local folder disappeared | It wasn't on the USB drive when the service started, or the drive had only videos at its top level |
| Videos at the top level of the drive don't play | The drive also has a valid schedule folder, which takes priority. Check with `--usb-sync-test` |
| Display stays on after hours | Check whether the signal is really `Off`, under Display control above. If it is, check the display's no-signal or power-saving settings |
| Screen is dark when it should show something | The signal is off because nothing is scheduled. Run `--test` and see Display control above |
| Projector does nothing | Run `--list-ports` and `--projector-test`, then check the commands and baud rate against the manual. A settings file replaces the automatic commands |
| Projector stays off after a short gap or restart | It may have ignored the start while cooling down. Use longer gaps between time windows |
| Service won't start | `sudo journalctl -u video-looper -n 50` |
| Nextcloud isn't updating | Run `--nextcloud-test` and read `sudo journalctl -u video-looper-nextcloud -n 50` |
| Local folder disappeared, with Nextcloud on | It wasn't in the Nextcloud folder at the last check |
| Wi-Fi won't connect | Show the password with Tab to check the keyboard layout. `nmcli device wifi list` shows what the Pi can see |
| Clock is wrong with NTP on | Check the Pi can reach the internet, and run `timedatectl status` |

Only warnings and errors are logged, to the system journal and not to a file, to reduce SD card wear. Errors from the boot menu aren't logged, because the login script discards them. The journal may not survive a reboot, depending on the system's configuration.

## How it works

Three systemd services run as `looper`. Two have permission to set the clock. `rtc-time-restore` sets the clock early in boot. `video-looper` then waits for the display driver, gives `looper` write access to the kernel's HDMI blank file, which is its only step running as root, then syncs from USB and runs the main loop. `video-looper-nextcloud` checks Nextcloud in the background when it's on, without any special permissions, and the main loop notices the new files.

The boot menu is a separate process started by the console login. When it needs the screen, it takes a file lock. The service then stops its video and keeps the HDMI signal and projector on until the lock is released, which the kernel does even if the menu crashes. The menu has no permission to set the clock, so it passes the entered time to the service.

| File | Responsibility |
|---|---|
| `video_looper.py` | Main loop and command line |
| `scheduler.py` | Parses folder names, including time windows, and decides what should play |
| `player.py` | VLC, and the display and projector around playback |
| `boot_menu.py` | Menu screens, key input, time prompts, demo mode |
| `time_entry.py` | The hold and time handoff between menu and service |
| `time_sync.py` | Reads and writes the RTC and system clock, and switches NTP |
| `network_setup.py` | Scans for and connects to Wi-Fi through `nmcli` |
| `usb_sync.py` | USB detection and safe copying |
| `nextcloud_sync.py` | Settings, WebDAV access, safe downloads and the background checks |
| `sync_plan.py` | Works out what to copy, rename and delete, for both sync sources |
| `hdmi_controller.py` | Switches the HDMI signal on and off |
| `projector_controller.py` | Finds the USB serial adapter, and sends projector commands |
| `console.py` | Writes to the HDMI console |
| `constants.py` | Shared settings, like paths, the check interval and the known projector brands |
| `video-looper.service`, `rtc-time-restore.service`, `video-looper-nextcloud.service` | The systemd services |
| `99-looper-rtc.rules` | Gives `looper` access to the RTC device |
| `50-looper-network-time.rules` | Lets `looper` change Wi-Fi and switch NTP |
| `install.sh`, `deploy.sh` | Set up a Pi, and update its code |

## Development

Tests use only Python's standard library plus `pyserial` and `requests`, and run on any Mac or Linux machine. They never touch the real clock, display, projector or VLC, and a local HTTP server stands in for Nextcloud.

```bash
python3 -m unittest
```

`deploy.sh` updates the code on a Pi that `install.sh` has already set up, using SSH key login and passwordless `sudo`. It only restarts the services if something changed, which interrupts the video and switches a connected projector off and on, and it refuses to restart if the USB sync would delete local folders. That check doesn't apply while Nextcloud is on, since USB video sync is off. It doesn't change the videos folder itself, and new modules need adding to the file lists in both `deploy.sh` and `install.sh`, which the tests check.

```bash
LOOPER_HOST=admin@192.168.1.140 ./deploy.sh --check
LOOPER_HOST=admin@192.168.1.140 ./deploy.sh
```

Other options are `--restart` to force a restart, and `--allow-usb-delete` to override the USB check.

## Security notes

- The services run as `looper` and don't need a network, unless you use NTP or Nextcloud. They hold the capability to set the clock. `video-looper` has one short step that runs as root at startup, to give `looper` write access to the HDMI blank file.
- `install.sh` gives `hwclock` that capability too, and the RTC rule gives `looper` the device, so the `looper` user can change the clock outside the services.
- The HDMI console logs in as `looper` automatically, so anyone with a keyboard on the Pi gets that user's shell. That includes `looper`'s permission to change Wi-Fi and NTP, through `50-looper-network-time.rules`.
- `admin`, when `install.sh` creates it, has passwordless `sudo`, so protect its SSH access.
- Anyone who can edit the Nextcloud folder controls what plays, and through projector settings files, which commands the projector receives.
- The Nextcloud password or share link is stored in `/home/looper/nextcloud.conf`, which only `looper` can read, but that includes anyone with a keyboard on the Pi. It isn't logged. Connections must use HTTPS, and server certificates are checked.
- Every USB serial adapter receives the projector commands unless a folder's settings say otherwise, so don't connect other serial devices without checking.

## License

Provided as-is for educational and personal use.
