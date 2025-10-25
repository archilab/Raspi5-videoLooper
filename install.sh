#!/bin/bash
# Installation script for Raspberry Pi Video Looper

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/home/pi/video_looper"
VIDEOS_DIR="/home/pi/videos"
SERVICE_NAME="video-looper"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo -e "${GREEN}=== Raspberry Pi Video Looper Installation ===${NC}"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}This script should not be run as root. Please run as pi user.${NC}"
   exit 1
fi

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo -e "${YELLOW}Warning: This script is designed for Raspberry Pi. Continue anyway? (y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
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
    ntp \
    ntpdate \
    systemd-timesyncd \
    python3-requests \
    python3-serial \
    python3-serial-tools

echo -e "${GREEN}Step 3: Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$VIDEOS_DIR"

echo -e "${GREEN}Step 4: Copying files...${NC}"
# Copy the video looper script
cp video_looper.py "$INSTALL_DIR/"
cp time_sync.py "$INSTALL_DIR/"
cp projector_controller.py "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/video_looper.py"
chmod +x "$INSTALL_DIR/time_sync.py"
chmod +x "$INSTALL_DIR/projector_controller.py"

# Copy the systemd service file
sudo cp video-looper.service "$SERVICE_FILE"

echo -e "${GREEN}Step 5: Setting up Python environment...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

echo -e "${GREEN}Step 6: Configuring time synchronization...${NC}"
# Enable systemd-timesyncd for automatic NTP sync
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

echo -e "${GREEN}Step 7: Configuring systemd service...${NC}"
# Update the service file to use the correct paths
sudo sed -i "s|/home/pi/video_looper|$INSTALL_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|/home/pi/videos|$VIDEOS_DIR|g" "$SERVICE_FILE"

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo -e "${GREEN}Step 8: Setting up permissions...${NC}"
# Ensure pi user owns the directories
sudo chown -R pi:pi "$INSTALL_DIR"
sudo chown -R pi:pi "$VIDEOS_DIR"

# Create log directory if it doesn't exist
sudo mkdir -p /var/log
sudo touch /var/log/video_looper.log
sudo chown pi:pi /var/log/video_looper.log

echo -e "${GREEN}Step 9: Testing installation...${NC}"
# Test the script
cd "$INSTALL_DIR"
python3 video_looper.py --test

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

echo -e "${GREEN}=== Installation Complete! ===${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Add your video files to the appropriate folders in $VIDEOS_DIR"
echo "2. Use the folder naming convention: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM"
echo "3. Start the service with: sudo systemctl start $SERVICE_NAME"
echo "4. Check status with: sudo systemctl status $SERVICE_NAME"
echo "5. View logs with: sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "${YELLOW}Service management commands:${NC}"
echo "  Start:   sudo systemctl start $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "${GREEN}The service will start automatically on boot.${NC}"
echo -e "${YELLOW}To disable autostart: sudo systemctl disable $SERVICE_NAME${NC}"
