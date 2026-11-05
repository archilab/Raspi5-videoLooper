#!/bin/bash
# Installation script for Raspberry Pi Video Looper

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration - using fixed user "looper"
INSTALL_DIR="/home/looper/video_looper"
VIDEOS_DIR="/home/looper/videos"
SERVICE_FILE="/etc/systemd/system/video-looper.service"

echo -e "${GREEN}Configuration:${NC}"
echo "  Service User: looper"
echo "  Install Directory: $INSTALL_DIR"
echo "  Videos Directory: $VIDEOS_DIR"
echo ""

# Check if running as root (using POSIX-compatible syntax)
if [ "$EUID" -eq 0 ]; then
   echo -e "${RED}This script should not be run as root. Please run as sudo (not root).${NC}"
   exit 1
fi

# Check if admin user exists
ADMIN_EXISTS=false
if id -u admin >/dev/null 2>&1; then
    ADMIN_EXISTS=true
    echo -e "${GREEN}✓ User 'admin' already exists${NC}"
else
    echo -e "${YELLOW}User 'admin' does not exist${NC}"
fi

# Check if looper user exists
LOOPER_EXISTS=false
if id -u looper >/dev/null 2>&1; then
    LOOPER_EXISTS=true
    echo -e "${GREEN}✓ User 'looper' already exists${NC}"
else
    echo -e "${YELLOW}User 'looper' does not exist${NC}"
fi

# If looper exists but admin doesn't, create admin and make it sudo user
if [ "$LOOPER_EXISTS" = true ] && [ "$ADMIN_EXISTS" = false ]; then
    echo -e "${GREEN}Creating admin user and configuring permissions...${NC}"
    
    # Create admin user with sudo privileges
    sudo useradd -m -s /bin/bash admin
    sudo usermod -a -G adm,tty,dialout,cdrom,audio,video,plugdev,games,users,input,netdev,gpio,i2c,spi,sudo,looper admin
    echo -e "${GREEN}✓ User 'admin' created${NC}"
    
    # Add admin to sudo group
    sudo usermod -aG sudo admin
    echo -e "${GREEN}✓ Added 'admin' to sudo group${NC}"
    
    # Remove looper from sudo group (if present)
    if groups looper | grep -q '\bsudo\b'; then
        sudo deluser looper sudo
        echo -e "${GREEN}✓ Removed 'looper' from sudo group${NC}"
    else
        echo -e "${GREEN}✓ 'looper' is not in sudo group${NC}"
    fi
    
    # Check for and remove looper from sudoers file (if present)
    if sudo grep -q "^looper" /etc/sudoers 2>/dev/null || sudo grep -q "^%looper" /etc/sudoers.d/* 2>/dev/null; then
        echo -e "${YELLOW}Warning: Found 'looper' entries in sudoers files. Manual review recommended.${NC}"
        echo -e "${YELLOW}Check /etc/sudoers and /etc/sudoers.d/* for 'looper' entries${NC}"
    fi
    
    # Create sudoers.d entry for admin (allow passwordless sudo)
    echo "admin ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/admin > /dev/null
    sudo chmod 0440 /etc/sudoers.d/admin
    echo -e "${GREEN}✓ Configured passwordless sudo for 'admin'${NC}"
    
    echo -e "${GREEN}✓ Admin user setup complete. Admin is now the sudo user.${NC}"
fi

# Check if looper user exists, create if not
if [ "$LOOPER_EXISTS" = false ]; then
    echo -e "${GREEN}Creating looper user...${NC}"
    sudo useradd -m -s /bin/bash looper
    echo -e "${GREEN}✓ User 'looper' created${NC}"
    LOOPER_EXISTS=true
fi

# Ensure looper is NOT in sudo group
if groups looper | grep -q '\bsudo\b'; then
    echo -e "${YELLOW}Removing 'looper' from sudo group...${NC}"
    sudo deluser looper sudo
    echo -e "${GREEN}✓ Removed 'looper' from sudo group${NC}"
fi

# Configure autologin for looper user on TTY1
echo -e "${GREEN}Configuring autologin for looper user...${NC}"
# Create systemd override directory
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d

# Create autologin configuration
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null <<'AUTOLOGIN'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin looper --noclear %I $TERM
AUTOLOGIN

echo -e "${GREEN}✓ Autologin configured for looper user${NC}"

# Create startup script that displays folder info after login
echo -e "${GREEN}Creating startup script for folder info display...${NC}"
sudo tee /home/looper/.bash_profile > /dev/null <<'STARTUP'
#!/bin/bash
# Display folder info on login (only on TTY1 to avoid multiple displays)
if [ "$(tty)" = "/dev/tty1" ] && [ -z "$FOLDER_INFO_DISPLAYED" ]; then
    export FOLDER_INFO_DISPLAYED=1
    if [ -f /home/looper/video_looper/video_looper.py ]; then
        /usr/bin/python3 /home/looper/video_looper/video_looper.py --display-folder-info 2>/dev/null || true
    fi
fi
STARTUP

sudo chown looper:looper /home/looper/.bash_profile
sudo chmod 644 /home/looper/.bash_profile
echo -e "${GREEN}✓ Startup script created${NC}"

# Reload systemd to apply autologin configuration
sudo systemctl daemon-reload
echo -e "${GREEN}✓ Systemd reloaded to apply autologin${NC}"

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo -e "${YELLOW}Warning: This script is designed for Raspberry Pi. Continue anyway? (y/N)${NC}"
    read -r response
    if [ "$response" != "y" ] && [ "$response" != "Y" ]; then
        exit 1
    fi
fi

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
sudo apt update
sudo apt upgrade -y

echo -e "${GREEN}Step 2: Installing required packages...${NC}"
sudo apt install -y \
    vlc \
    python3 \
    python3-pip \
    python3-venv \
    git \
    ffmpeg \
    python3-requests \
    python3-serial \
    cec-utils \
    util-linux \
    util-linux-extra  

sudo apt-get install -y pmount

echo -e "${GREEN}Step 3: Configuring USB automount...${NC}"

# Create mount script /usr/local/bin/cpmount
echo -e "${GREEN}Creating USB mount script...${NC}"
sudo tee /usr/local/bin/cpmount > /dev/null <<'CPMOUNT'
#!/bin/bash
if mountpoint -q /media/usb1
then
   if mountpoint -q /media/usb2
   then
      if mountpoint -q /media/usb3
      then
         if mountpoint -q /media/usb4
         then
             echo "No mountpoints available!"
             #You can add more if you need
         else
             /usr/bin/pmount --umask 000 --noatime -w --sync $1 usb4
         fi
      else
         /usr/bin/pmount --umask 000 --noatime -w --sync $1 usb3
      fi
   else
      /usr/bin/pmount --umask 000 --noatime -w --sync $1 usb2
   fi
else
   /usr/bin/pmount --umask 000 --noatime -w --sync $1 usb1
fi
CPMOUNT

# Make mount script executable
sudo chmod +x /usr/local/bin/cpmount
echo -e "${GREEN}✓ USB mount script created${NC}"

# Create udev rule
echo -e "${GREEN}Creating udev rule for USB automount...${NC}"
sudo tee /etc/udev/rules.d/usbstick.rules > /dev/null <<'UDEV'
ACTION=="add", KERNEL=="sd[a-z][0-9]", TAG+="systemd", ENV{SYSTEMD_WANTS}="usbstick-handler@%k"
UDEV

echo -e "${GREEN}✓ Udev rule created${NC}"

# Create systemd service
echo -e "${GREEN}Creating systemd service for USB automount...${NC}"
sudo tee /lib/systemd/system/usbstick-handler@.service > /dev/null <<'SERVICE'
[Unit]
Description=Mount USB sticks
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/cpmount /dev/%I
ExecStop=/usr/bin/pumount /dev/%I
SERVICE

echo -e "${GREEN}✓ Systemd service created${NC}"

# Reload systemd and udev
echo -e "${GREEN}Reloading systemd and udev...${NC}"
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger

echo -e "${GREEN}✓ USB automount configured${NC}"

echo -e "${GREEN}Step 4: Creating directories...${NC}"
sudo mkdir -p "$INSTALL_DIR"
sudo mkdir -p "$VIDEOS_DIR"
# Set ownership immediately so we can work with the directories
sudo chown looper:looper "$INSTALL_DIR"
sudo chown looper:looper "$VIDEOS_DIR"

echo -e "${GREEN}Step 5: Copying files...${NC}"
# Copy the video looper script (force overwrite) - use sudo since directory is owned by looper
sudo cp -f video_looper.py "$INSTALL_DIR/"
sudo cp -f time_sync.py "$INSTALL_DIR/"
sudo cp -f projector_controller.py "$INSTALL_DIR/"
sudo cp -f hdmi_controller.py "$INSTALL_DIR/"
sudo cp -f usb_sync.py "$INSTALL_DIR/"
sudo cp -f constants.py "$INSTALL_DIR/"
sudo cp -f config.conf "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/video_looper.py"
sudo chmod +x "$INSTALL_DIR/time_sync.py"
sudo chmod +x "$INSTALL_DIR/projector_controller.py"
sudo chmod +x "$INSTALL_DIR/hdmi_controller.py"
sudo chmod +x "$INSTALL_DIR/usb_sync.py"
sudo chmod +x "$INSTALL_DIR/constants.py"

echo -e "${GREEN}Step 6: Setting up Python environment...${NC}"
# Create Python virtual environment as looper user
sudo -u looper bash -c "cd '$INSTALL_DIR' && python3 -m venv venv"

# Check if virtual environment was created successfully
if [ -f "$INSTALL_DIR/venv/bin/activate" ]; then
    echo -e "${GREEN}✓ Virtual environment created successfully${NC}"
    # Use the virtual environment's pip directly instead of sourcing
    sudo -u looper bash -c "cd '$INSTALL_DIR' && ./venv/bin/pip install --upgrade pip"
else
    echo -e "${YELLOW}⚠ Virtual environment creation failed, using system pip${NC}"
    pip3 install --upgrade pip
fi

echo -e "${GREEN}Step 7: Configuring RTC-only time synchronization (NTP disabled)...${NC}"

# Disable systemd-timesyncd (NTP)
echo -e "${GREEN}Disabling NTP (systemd-timesyncd)...${NC}"
sudo systemctl stop systemd-timesyncd 2>/dev/null || true
sudo systemctl disable systemd-timesyncd 2>/dev/null || true
sudo timedatectl set-ntp false 2>/dev/null || true
echo -e "${GREEN}✓ NTP disabled${NC}"

# Ensure util-linux (hwclock) is available
sudo apt-get update -y
sudo apt-get install -y util-linux

# Set capabilities on hwclock so unprivileged user can use it
echo -e "${GREEN}Setting capabilities on hwclock for unprivileged access...${NC}"
HWCLOCK_PATH=$(which hwclock 2>/dev/null || echo "/usr/sbin/hwclock")
if [ -f "$HWCLOCK_PATH" ]; then
    sudo setcap cap_sys_time+ep "$HWCLOCK_PATH"
    echo -e "${GREEN}✓ Capabilities set on $HWCLOCK_PATH${NC}"
else
    # Try alternative locations
    for path in /usr/sbin/hwclock /usr/bin/hwclock /sbin/hwclock /bin/hwclock; do
        if [ -f "$path" ]; then
            sudo setcap cap_sys_time+ep "$path"
            echo -e "${GREEN}✓ Capabilities set on $path${NC}"
            break
        fi
    done
fi

# Let the looper service write the RTC when the time is set from the boot menu
echo -e "${GREEN}Giving looper access to the RTC device...${NC}"
sudo install -o root -g root -m 644 99-looper-rtc.rules /etc/udev/rules.d/99-looper-rtc.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=rtc --action=change

# Configure system to use RTC only
echo -e "${GREEN}Configuring system for RTC-only mode...${NC}"
# Ensure RTC is set to local time (not UTC) if needed
# This is typically already configured on Raspberry Pi OS

echo -e "${GREEN}✓ RTC-only time synchronization configured${NC}"

echo -e "${GREEN}Step 8: Configuring systemd service...${NC}"

# Check if service is already running and stop it before updating
SERVICE_WAS_RUNNING=false
if [ -f "$SERVICE_FILE" ] && systemctl is-active --quiet video-looper 2>/dev/null; then
    echo -e "${YELLOW}Service is currently running, stopping it before updating...${NC}"
    SERVICE_WAS_RUNNING=true
    sudo systemctl stop video-looper || true
fi

# Get user ID for XDG_RUNTIME_DIR
LOOPER_USER_ID=$(id -u looper 2>/dev/null || echo "1000")

# Verify video-looper.service exists in current directory
if [ ! -f "video-looper.service" ]; then
    echo -e "${RED}Error: video-looper.service file not found in current directory!${NC}"
    echo -e "${RED}Please run install.sh from the directory containing video-looper.service${NC}"
    exit 1
fi

# Install RTC time restore service (runs early at boot)
if [ -f "rtc-time-restore.service" ]; then
    echo -e "${GREEN}Installing RTC time restore service...${NC}"
    RTC_SERVICE_FILE="/etc/systemd/system/rtc-time-restore.service"
    sudo cp -f rtc-time-restore.service "$RTC_SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable rtc-time-restore.service
    echo -e "${GREEN}✓ RTC time restore service installed and enabled${NC}"
else
    echo -e "${YELLOW}Warning: rtc-time-restore.service not found, skipping...${NC}"
fi

# Always reinstall the service file from the installation folder
echo -e "${GREEN}Installing service file from installation folder...${NC}"
sudo cp -f video-looper.service "$SERVICE_FILE"

# Update XDG_RUNTIME_DIR with actual user ID (only dynamic value that can vary)
echo -e "${GREEN}Updating XDG_RUNTIME_DIR with actual user ID...${NC}"
sudo sed -i "s|/run/user/1000|/run/user/$LOOPER_USER_ID|g" "$SERVICE_FILE"

# Verify WorkingDirectory has absolute path
if ! sudo grep -q "^WorkingDirectory=/.*$" "$SERVICE_FILE"; then
    echo -e "${RED}Error: WorkingDirectory does not have absolute path!${NC}"
    echo -e "${YELLOW}Current WorkingDirectory line:${NC}"
    sudo grep "^WorkingDirectory=" "$SERVICE_FILE"
    exit 1
fi

echo -e "${GREEN}✓ Service file installed and configured${NC}"

# Config file already has correct paths (no replacement needed)

# Reload systemd and enable the service
echo -e "${GREEN}Reloading systemd daemon...${NC}"
sudo systemctl daemon-reload

echo -e "${GREEN}Enabling service for auto-start on boot...${NC}"
sudo systemctl enable video-looper

# Always start the service after enabling
echo -e "${GREEN}Starting service...${NC}"
sudo systemctl start video-looper

# Wait a moment and check if it started successfully
sleep 3
if systemctl is-active --quiet video-looper 2>/dev/null; then
    echo -e "${GREEN}✓ Service started successfully${NC}"
else
    echo -e "${YELLOW}⚠ Service may not have started correctly. Checking status...${NC}"
    sudo systemctl status video-looper --no-pager -l || true
    echo -e "${YELLOW}Check logs with: sudo journalctl -u video-looper -n 50${NC}"
fi

echo -e "${GREEN}Step 9: Setting up permissions...${NC}"
# Ensure looper user owns the directories
sudo chown -R looper:looper "$INSTALL_DIR"
sudo chown -R looper:looper "$VIDEOS_DIR"

# Create log directory if it doesn't exist
sudo mkdir -p /var/log
sudo touch /var/log/video_looper.log
sudo chown looper:looper /var/log/video_looper.log

# Ensure XDG_RUNTIME_DIR exists for looper user (required for systemd user services)
LOOPER_USER_ID=$(id -u looper 2>/dev/null || echo "1000")
if [ ! -d "/run/user/$LOOPER_USER_ID" ]; then
    echo -e "${GREEN}Creating runtime directory for looper user...${NC}"
    sudo mkdir -p "/run/user/$LOOPER_USER_ID"
    sudo chown looper:looper "/run/user/$LOOPER_USER_ID"
    sudo chmod 0700 "/run/user/$LOOPER_USER_ID"
    echo -e "${GREEN}✓ Runtime directory created${NC}"
fi

echo -e "${GREEN}Step 10: Testing installation...${NC}"
# Test the script as looper user
sudo -u looper bash -c "cd '$INSTALL_DIR' && python3 video_looper.py --test"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Installation test successful!${NC}"
else
    echo -e "${RED}✗ Installation test failed!${NC}"
    exit 1
fi

echo -e "${GREEN}Step 11: Creating example folder structure...${NC}"
# Create example folders with different schedules
mkdir -p "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800"
mkdir -p "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000"
mkdir -p "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200"

# Create placeholder files
touch "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800/example_video.mp4"
touch "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000/example_video.mp4"
touch "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200/example_video.mp4"

# Create projector configuration examples
echo "Creating projector configuration examples..."

cat > "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800/projector.txt" << 'EOF'
# Projector configuration for January videos
enable_projector=true
serial_port=/dev/ttyUSB0
baud_rate=9600
timeout=5
start_command=~0000 1
stop_command=~0000 0
start_delay=2
stop_delay=1
video_start_delay=5
wait_for_response=false
EOF

cat > "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000/projector.txt" << 'EOF'
# Projector configuration for February videos
enable_projector=false
EOF

cat > "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200/projector.txt" << 'EOF'
# Projector configuration for December videos
enable_projector=true
serial_port=/dev/ttyUSB0
baud_rate=9600
timeout=5
start_command=~0000 1
stop_command=~0000 0
start_delay=2
stop_delay=1
video_start_delay=5
wait_for_response=false
EOF

echo -e "${GREEN}=== Installation Complete! ===${NC}"
echo ""
echo -e "${GREEN}Example folder structure created:${NC}"
echo "$VIDEOS_DIR/"
echo "├── 2024-01-01_to_2024-01-31_0900_to_1800/  (January: 9AM-6PM)"
echo "│   ├── example_video.mp4"
echo "│   └── projector.txt  (projector enabled)"
echo "├── 2024-02-01_to_2024-02-29_0800_to_2000/  (February: 8AM-8PM)"
echo "│   ├── example_video.mp4"
echo "│   └── projector.txt  (projector disabled)"
echo "└── 2024-12-01_to_2024-12-31_1000_to_2200/  (December: 10AM-10PM)"
echo "    ├── example_video.mp4"
echo "    └── projector.txt  (projector enabled)"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Add your video files to the appropriate folders in $VIDEOS_DIR"
echo "2. Use the folder naming convention: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM"
echo "3. Start the service with: sudo systemctl start video-looper"
echo "4. Check status with: sudo systemctl status video-looper"
echo "5. View logs with: sudo journalctl -u video-looper -f"
echo ""
echo -e "${YELLOW}Service management commands:${NC}"
echo "  Start:   sudo systemctl start video-looper"
echo "  Stop:    sudo systemctl stop video-looper"
echo "  Restart: sudo systemctl restart video-looper"
echo "  Status:  sudo systemctl status video-looper"
echo "  Logs:    sudo journalctl -u video-looper -f"
echo ""
echo -e "${GREEN}The service will start automatically on boot.${NC}"
echo -e "${YELLOW}To disable autostart: sudo systemctl disable video-looper${NC}"
