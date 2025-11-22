#!/bin/bash
# Troubleshooting script for Raspberry Pi Video Looper

echo "=== Video Looper Troubleshooting Script ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Paths for looper user
VIDEO_LOOPER_DIR="/home/looper/video_looper"
VIDEOS_DIR="/home/looper/videos"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check service status
check_service() {
    echo -e "${YELLOW}Checking service status...${NC}"
    if systemctl is-active --quiet video-looper; then
        echo -e "${GREEN}✓ Service is running${NC}"
    else
        echo -e "${RED}✗ Service is not running${NC}"
        echo "Try: sudo systemctl start video-looper"
    fi
    
    if systemctl is-enabled --quiet video-looper; then
        echo -e "${GREEN}✓ Service is enabled (will start on boot)${NC}"
    else
        echo -e "${YELLOW}⚠ Service is not enabled${NC}"
        echo "Try: sudo systemctl enable video-looper"
    fi
}

# Function to check dependencies
check_dependencies() {
    echo -e "${YELLOW}Checking dependencies...${NC}"
    
    if command_exists vlc; then
        echo -e "${GREEN}✓ VLC is installed${NC}"
        vlc --version | head -1
    else
        echo -e "${RED}✗ VLC is not installed${NC}"
        echo "Install with: sudo apt install vlc"
    fi
    
    if command_exists python3; then
        echo -e "${GREEN}✓ Python3 is installed${NC}"
        python3 --version
    else
        echo -e "${RED}✗ Python3 is not installed${NC}"
        echo "Install with: sudo apt install python3"
    fi
    
    if python3 -c "import serial" 2>/dev/null; then
        echo -e "${GREEN}✓ pyserial is installed${NC}"
    else
        echo -e "${RED}✗ pyserial is not installed${NC}"
        echo "Install with: sudo apt install python3-serial"
    fi
    
    if systemctl is-active --quiet systemd-timesyncd; then
        echo -e "${GREEN}✓ systemd-timesyncd is running${NC}"
    else
        echo -e "${YELLOW}⚠ systemd-timesyncd is not running${NC}"
        echo "Start with: sudo systemctl start systemd-timesyncd"
    fi
}

# Function to check files and permissions
check_files() {
    echo -e "${YELLOW}Checking files and permissions...${NC}"
    
    if [ -f "$VIDEO_LOOPER_DIR/video_looper.py" ]; then
        echo -e "${GREEN}✓ Main script exists${NC}"
        if [ -x "$VIDEO_LOOPER_DIR/video_looper.py" ]; then
            echo -e "${GREEN}✓ Main script is executable${NC}"
        else
            echo -e "${RED}✗ Main script is not executable${NC}"
            echo "Fix with: chmod +x $VIDEO_LOOPER_DIR/video_looper.py"
        fi
    else
        echo -e "${RED}✗ Main script not found${NC}"
        echo "Expected: $VIDEO_LOOPER_DIR/video_looper.py"
    fi
    
    if [ -d "$VIDEOS_DIR" ]; then
        echo -e "${GREEN}✓ Videos directory exists${NC}"
        video_count=$(find "$VIDEOS_DIR" -name "*.mp4" -o -name "*.avi" -o -name "*.mov" -o -name "*.mkv" | wc -l)
        echo "  Found $video_count video files"
    else
        echo -e "${RED}✗ Videos directory not found${NC}"
        echo "Create with: mkdir -p $VIDEOS_DIR"
    fi
    
    if [ -f "/etc/systemd/system/video-looper.service" ]; then
        echo -e "${GREEN}✓ Service file exists${NC}"
    else
        echo -e "${RED}✗ Service file not found${NC}"
        echo "Expected: /etc/systemd/system/video-looper.service"
    fi
}

# Function to check logs
check_logs() {
    echo -e "${YELLOW}Checking recent logs...${NC}"
    
    if [ -f "/var/log/video_looper.log" ]; then
        echo -e "${GREEN}✓ Log file exists${NC}"
        echo "Last 10 lines:"
        tail -10 /var/log/video_looper.log
    else
        echo -e "${YELLOW}⚠ Log file not found${NC}"
    fi
    
    echo ""
    echo "Recent systemd logs:"
    journalctl -u video-looper --since "1 hour ago" --no-pager | tail -10
}

# Function to test folder parsing
test_folder_parsing() {
    echo -e "${YELLOW}Testing folder parsing...${NC}"
    
    cd "$VIDEO_LOOPER_DIR"
    if python3 video_looper.py --test; then
        echo -e "${GREEN}✓ Folder parsing test passed${NC}"
    else
        echo -e "${RED}✗ Folder parsing test failed${NC}"
    fi
}

# Function to check time synchronization
check_time_sync() {
    echo -e "${YELLOW}Checking time synchronization...${NC}"
    
    cd "$VIDEO_LOOPER_DIR"
    if python3 video_looper.py --time-status; then
        echo -e "${GREEN}✓ Time sync status retrieved${NC}"
    else
        echo -e "${RED}✗ Time sync status check failed${NC}"
    fi
    
    echo ""
    echo "System time status:"
    timedatectl status | grep -E "(NTP|RTC|Time zone)"
    
    echo ""
    echo "Testing time sync:"
    if python3 time_sync.py --test; then
        echo -e "${GREEN}✓ Time sync test passed${NC}"
    else
        echo -e "${RED}✗ Time sync test failed${NC}"
    fi
}

# Function to check projector configuration
check_projector() {
    echo -e "${YELLOW}Checking projector configuration...${NC}"
    
    cd "$VIDEO_LOOPER_DIR"
    echo "Available serial ports:"
    if python3 video_looper.py --list-ports; then
        echo -e "${GREEN}✓ Serial ports listed successfully${NC}"
    else
        echo -e "${RED}✗ Failed to list serial ports${NC}"
    fi
    
    echo ""
    echo "Testing projector connection:"
    if python3 video_looper.py --projector-test; then
        echo -e "${GREEN}✓ Projector test passed${NC}"
    else
        echo -e "${RED}✗ Projector test failed${NC}"
    fi
    
    echo ""
    echo "Projector configuration files found:"
    find "$VIDEOS_DIR" -name "projector.txt" -o -name "projector.conf" -o -name "config.txt" 2>/dev/null | while read file; do
        echo "  $file"
        if [ -f "$file" ]; then
            echo "    Content preview:"
            head -5 "$file" | sed 's/^/      /'
        fi
    done
}

# Function to check display
check_display() {
    echo -e "${YELLOW}Checking display settings...${NC}"
    
    if [ -n "$DISPLAY" ]; then
        echo -e "${GREEN}✓ DISPLAY variable is set: $DISPLAY${NC}"
    else
        echo -e "${RED}✗ DISPLAY variable is not set${NC}"
        echo "This may cause VLC to fail"
    fi
    
    if command_exists xrandr; then
        echo "Available displays:"
        xrandr --query | grep " connected"
    fi
}

# Function to show current time and active folders
show_current_status() {
    echo -e "${YELLOW}Current status...${NC}"
    echo "Current date: $(date '+%Y-%m-%d')"
    echo "Current time: $(date '+%H:%M')"
    echo ""
    
    echo "Folders in $VIDEOS_DIR:"
    if [ -d "$VIDEOS_DIR" ]; then
        for folder in "$VIDEOS_DIR"/*; do
            if [ -d "$folder" ]; then
                folder_name=$(basename "$folder")
                echo "  $folder_name"
            fi
        done
    else
        echo "  No videos directory found"
    fi
}

# Main troubleshooting routine
echo "Running comprehensive system check..."
echo ""

check_dependencies
echo ""
check_files
echo ""
check_service
echo ""
check_display
echo ""
show_current_status
echo ""
test_folder_parsing
echo ""
check_time_sync
echo ""
check_projector
echo ""
check_logs

echo ""
echo "=== Troubleshooting Complete ==="
echo ""
echo "Common fixes:"
echo "1. If service won't start: sudo systemctl restart video-looper"
echo "2. If VLC fails: sudo apt install --reinstall vlc"
echo "3. If permissions wrong: sudo chown -R looper:looper $VIDEOS_DIR"
echo "4. If no videos found: Check folder naming convention"
echo "5. If display issues: export DISPLAY=:0"
echo ""
echo "For more help, check the README.md file"
