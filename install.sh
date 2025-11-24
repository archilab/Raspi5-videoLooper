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
    cec-utils 

sudo apt-get install -y pmount

echo -e "${GREEN}Step 3: Creating directories...${NC}"
sudo mkdir -p "$INSTALL_DIR"
sudo mkdir -p "$VIDEOS_DIR"
# Set ownership immediately so we can work with the directories
sudo chown looper:looper "$INSTALL_DIR"
sudo chown looper:looper "$VIDEOS_DIR"

echo -e "${GREEN}Step 4: Copying files...${NC}"
# Copy the video looper script (force overwrite) - use sudo since directory is owned by looper
sudo cp -f video_looper.py "$INSTALL_DIR/"
sudo cp -f time_sync.py "$INSTALL_DIR/"
sudo cp -f projector_controller.py "$INSTALL_DIR/"
sudo cp -f hdmi_controller.py "$INSTALL_DIR/"
sudo cp -f usb_sync.py "$INSTALL_DIR/"
sudo cp -f config.conf "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/video_looper.py"
sudo chmod +x "$INSTALL_DIR/time_sync.py"
sudo chmod +x "$INSTALL_DIR/projector_controller.py"
sudo chmod +x "$INSTALL_DIR/hdmi_controller.py"
sudo chmod +x "$INSTALL_DIR/usb_sync.py"

echo -e "${GREEN}Step 5: Setting up Python environment...${NC}"
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

echo -e "${GREEN}Step 6: Configuring time synchronization...${NC}"
# Enable systemd-timesyncd for automatic NTP sync (already included in Raspberry Pi OS)
sudo systemctl enable systemd-timesyncd
sudo systemctl start systemd-timesyncd

# Configure NTP servers
sudo tee /etc/systemd/timesyncd.conf > /dev/null <<EOF
[Time]
NTP=pool.ntp.org time.google.com time.cloudflare.com
FallbackNTP=time.nist.gov
PollIntervalMinSec=32
PollIntervalMaxSec=2048
EOF

# Restart timesyncd to apply new configuration
sudo systemctl restart systemd-timesyncd

echo -e "${GREEN}✓ Time synchronization configured${NC}"

echo -e "${GREEN}Step 7: Configuring systemd service...${NC}"

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

# Restart or start the service
if [ "$SERVICE_WAS_RUNNING" = true ]; then
    echo -e "${GREEN}Restarting service with new configuration...${NC}"
    sudo systemctl start video-looper
    
    # Wait a moment and check if it started successfully
    sleep 2
    if systemctl is-active --quiet video-looper; then
        echo -e "${GREEN}✓ Service restarted successfully${NC}"
    else
        echo -e "${YELLOW}⚠ Service may not have started correctly. Check status with: sudo systemctl status video-looper${NC}"
    fi
else
    echo -e "${GREEN}Service is enabled and ready.${NC}"
    echo -e "${YELLOW}  Start it manually with: sudo systemctl start video-looper${NC}"
    echo -e "${YELLOW}  Or it will start automatically on the next reboot.${NC}"
fi

echo -e "${GREEN}Step 8: Setting up permissions...${NC}"
# Ensure looper user owns the directories
sudo chown -R looper:looper "$INSTALL_DIR"
sudo chown -R looper:looper "$VIDEOS_DIR"

# Create log directory if it doesn't exist
sudo mkdir -p /var/log
sudo touch /var/log/video_looper.log
sudo chown looper:looper /var/log/video_looper.log

echo -e "${GREEN}Step 9: Testing installation...${NC}"
# Test the script as looper user
sudo -u looper bash -c "cd '$INSTALL_DIR' && python3 video_looper.py --test"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Installation test successful!${NC}"
else
    echo -e "${RED}✗ Installation test failed!${NC}"
    exit 1
fi

echo -e "${GREEN}Step 10: Creating example folder structure...${NC}"
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
start_command=PWR ON
stop_command=PWR OFF
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
start_command=PWR ON
stop_command=PWR OFF
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
