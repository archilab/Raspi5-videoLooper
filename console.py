#!/usr/bin/env python3
"""Show text on the HDMI console (tty1)"""

CONSOLE_PATH = '/dev/tty1'
CLEAR_SCREEN = '\033[2J\033[H\033[0m'  # Clear, move cursor home, reset formatting


def show_on_console(text):
    """
    Replace what is on the console with text.
    Returns False if it couldn't be shown; callers can usually carry on without it.
    """
    try:
        with open(CONSOLE_PATH, 'w') as console:
            console.write(CLEAR_SCREEN + text)
        return True
    except (OSError, ValueError):
        return False
