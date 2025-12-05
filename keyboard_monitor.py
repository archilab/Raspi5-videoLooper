#!/usr/bin/env python3
"""
Keyboard Monitor Module
Detects keyboard input for test mode trigger (Ctrl+F1)
Uses evdev for Linux input event detection
"""

import logging
import threading
from pathlib import Path
# Import key codes from constants (fallback values)
# Will use evdev ecodes if available

try:
    from evdev import InputDevice, categorize, ecodes
    EVDEV_AVAILABLE = True
    # Use ecodes constants if available, otherwise fall back to numeric codes
    KEY_CTRL = getattr(ecodes, 'KEY_LEFTCTRL', 29)
    KEY_F1 = getattr(ecodes, 'KEY_F1', 59)
except ImportError:
    EVDEV_AVAILABLE = False
    KEY_CTRL = 29  # Left Ctrl key code (Linux input event)
    KEY_F1 = 59    # F1 key code (Linux input event)

class KeyboardMonitor:
    def __init__(self, callback, log_file="/var/log/video_looper.log"):
        """
        Initialize keyboard monitor
        Args:
            callback: Function to call when Ctrl+F1 is detected
            log_file: Log file path
        """
        self.logger = logging.getLogger(__name__)
        self.callback = callback
        self.monitoring = False
        self.monitor_thread = None
        self.input_device = None
        self.ctrl_pressed = False
        self.f1_pressed = False
        
        if not EVDEV_AVAILABLE:
            self.logger.warning("evdev not available. Keyboard monitoring disabled.")
    
    def _find_keyboard_device(self):
        """Find a keyboard input device"""
        input_devices = Path('/dev/input')
        
        if not input_devices.exists():
            return None
        
        # Try common keyboard device names
        for device_path in input_devices.glob('event*'):
            try:
                device = InputDevice(str(device_path))
                # Check if device has keyboard capabilities
                if ecodes.EV_KEY in device.capabilities():
                    # Check if it has the keys we need (Ctrl and F1)
                    key_caps = device.capabilities()[ecodes.EV_KEY]
                    if KEY_CTRL in key_caps and KEY_F1 in key_caps:
                        return device
            except (OSError, PermissionError):
                continue
        
        # Fallback: try first available event device
        for device_path in sorted(input_devices.glob('event*')):
            try:
                device = InputDevice(str(device_path))
                if ecodes.EV_KEY in device.capabilities():
                    return device
            except (OSError, PermissionError):
                continue
        
        return None
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        if not EVDEV_AVAILABLE:
            return
        
        self.input_device = self._find_keyboard_device()
        
        if not self.input_device:
            self.logger.warning("No keyboard input device found. Test mode trigger disabled.")
            return
        
        self.logger.info(f"Monitoring keyboard: {self.input_device.name}")
        
        try:
            for event in self.input_device.read_loop():
                if not self.monitoring:
                    break
                
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    
                    # Track Ctrl key state
                    if key_event.scancode == KEY_CTRL:
                        self.ctrl_pressed = (key_event.keystate == key_event.key_down)
                    
                    # Track F1 key state
                    elif key_event.scancode == KEY_F1:
                        if key_event.keystate == key_event.key_down:
                            self.f1_pressed = True
                        elif key_event.keystate == key_event.key_up:
                            # Check if Ctrl+F1 was pressed (Ctrl still held when F1 released)
                            if self.ctrl_pressed and self.f1_pressed:
                                self.logger.info("Ctrl+F1 detected - triggering test mode")
                                try:
                                    self.callback()
                                except Exception as e:
                                    self.logger.error(f"Error in test mode callback: {e}")
                            self.f1_pressed = False
                    
        except OSError as e:
            self.logger.error(f"Error reading keyboard input: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in keyboard monitor: {e}")
        finally:
            if self.input_device:
                try:
                    self.input_device.close()
                except Exception:
                    pass
    
    def start(self):
        """Start keyboard monitoring in background thread"""
        if not EVDEV_AVAILABLE:
            return False
        
        if self.monitoring:
            return True
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        return True
    
    def stop(self):
        """Stop keyboard monitoring"""
        self.monitoring = False
        if self.input_device:
            try:
                self.input_device.close()
            except Exception:
                pass
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
    
    def is_available(self):
        """Check if keyboard monitoring is available"""
        return EVDEV_AVAILABLE and self._find_keyboard_device() is not None

