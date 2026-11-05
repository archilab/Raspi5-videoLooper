#!/bin/bash
# Quick Start Guide for Raspberry Pi Video Looper

echo "=== Raspberry Pi Video Looper - Quick Start Guide ==="
echo ""
echo "This script will help you set up example folders and test the system."
echo ""

# Create example folders with different schedules
VIDEOS_DIR="/home/looper/videos"

echo "Creating example folder structure..."

# Create folders for different months/seasons
mkdir -p "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800"
mkdir -p "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000"
mkdir -p "$VIDEOS_DIR/2024-06-01_to_2024-06-30_0700_to_2100"
mkdir -p "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200"

# Create some test video files (empty files for demonstration)
echo "Creating example video files..."

# January folder - Winter/New Year content
touch "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800/new_year_greetings.mp4"
touch "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800/winter_sale.mp4"
touch "$VIDEOS_DIR/2024-01-01_to_2024-01-31_0900_to_1800/company_intro.mp4"

# February folder - Valentine's Day content
touch "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000/valentine_promo.mp4"
touch "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000/february_sale.mp4"
touch "$VIDEOS_DIR/2024-02-01_to_2024-02-29_0800_to_2000/love_collection.mp4"

# June folder - Summer content
touch "$VIDEOS_DIR/2024-06-01_to_2024-06-30_0700_to_2100/summer_collection.mp4"
touch "$VIDEOS_DIR/2024-06-01_to_2024-06-30_0700_to_2100/beach_vacation.mp4"
touch "$VIDEOS_DIR/2024-06-01_to_2024-06-30_0700_to_2100/sunny_days.mp4"

# December folder - Christmas/Holiday content
touch "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200/christmas_greetings.mp4"
touch "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200/holiday_sale.mp4"
touch "$VIDEOS_DIR/2024-12-01_to_2024-12-31_1000_to_2200/new_year_countdown.mp4"

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

cat > "$VIDEOS_DIR/2024-06-01_to_2024-06-30_0700_to_2100/projector.txt" << 'EOF'
# Projector configuration for June videos
enable_projector=true
serial_port=/dev/ttyUSB0
baud_rate=19200
timeout=5
start_command=POWER ON
stop_command=POWER OFF
start_delay=3
stop_delay=2
video_start_delay=8
wait_for_response=true
EOF

echo "✓ Example folder structure created!"
echo ""
echo "Folder structure:"
echo "$VIDEOS_DIR/"
echo "├── 2024-01-01_to_2024-01-31_0900_to_1800/  (January: 9AM-6PM)"
echo "│   ├── new_year_greetings.mp4"
echo "│   ├── winter_sale.mp4"
echo "│   ├── company_intro.mp4"
echo "│   └── projector.txt  (projector enabled)"
echo "├── 2024-02-01_to_2024-02-29_0800_to_2000/  (February: 8AM-8PM)"
echo "│   ├── valentine_promo.mp4"
echo "│   ├── february_sale.mp4"
echo "│   ├── love_collection.mp4"
echo "│   └── projector.txt  (projector disabled)"
echo "├── 2024-06-01_to_2024-06-30_0700_to_2100/  (June: 7AM-9PM)"
echo "│   ├── summer_collection.mp4"
echo "│   ├── beach_vacation.mp4"
echo "│   ├── sunny_days.mp4"
echo "│   └── projector.txt  (projector enabled)"
echo "└── 2024-12-01_to_2024-12-31_1000_to_2200/  (December: 10AM-10PM)"
echo "    ├── christmas_greetings.mp4"
echo "    ├── holiday_sale.mp4"
echo "    └── new_year_countdown.mp4"
echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Replace the empty .mp4 files with your actual video files"
echo "2. Test the system:"
echo "   cd /home/looper/video_looper"
echo "   sudo -u looper python3 video_looper.py --test"
echo ""
echo "3. Start the service:"
echo "   sudo systemctl start video-looper"
echo ""
echo "4. Check status:"
echo "   sudo systemctl status video-looper"
echo ""
echo "5. View logs:"
echo "   sudo journalctl -u video-looper -f"
echo ""
echo "=== Folder Naming Convention ==="
echo "Format: YYYY-MM-DD_to_YYYY-MM-DD_HHMM_to_HHMM"
echo ""
echo "Examples:"
echo "• 2024-01-01_to_2024-01-31_0900_to_1800  (January, 9AM-6PM)"
echo "• 2024-12-01_to_2024-12-31_1000_to_2200  (December, 10AM-10PM)"
echo "• 2024-06-15_to_2024-06-30_0800_to_2000  (June 15-30, 8AM-8PM)"
echo "• 2024-12-01_to_2024-12-03_2200_to_0600  (Overnight: Dec 1 10PM until Dec 4 6AM)"
echo ""
echo "=== Current Date/Time Check ==="
echo "Current date: $(date '+%Y-%m-%d')"
echo "Current time: $(date '+%H:%M')"
echo ""
echo "Based on current date/time:"
python3 /home/looper/video_looper/video_looper.py --test --videos-path "$VIDEOS_DIR"

echo ""
echo "=== Quick Commands ==="
echo "Test system:     sudo -u looper python3 /home/looper/video_looper/video_looper.py --test"
echo "Start service:   sudo systemctl start video-looper"
echo "Stop service:    sudo systemctl stop video-looper"
echo "Restart service: sudo systemctl restart video-looper"
echo "Check status:    sudo systemctl status video-looper"
echo "View logs:       sudo journalctl -u video-looper -f"
echo ""
echo "Setup complete! Replace the example video files with your actual videos."
