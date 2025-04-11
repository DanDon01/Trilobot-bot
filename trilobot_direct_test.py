#!/usr/bin/env python3
"""
Trilobot Direct Test

This script directly imports and tests the Trilobot library without
any of the project's other components that might be causing issues.
"""

import time
import sys
import traceback

print("Python version:", sys.version)
print("Python executable path:", sys.executable)
print("\nTesting RPi.GPIO availability...")

try:
    import RPi.GPIO as GPIO
    print("RPi.GPIO imported successfully!")
    print("RPi.GPIO version:", GPIO.VERSION)
except ImportError as e:
    print(f"ERROR: Failed to import RPi.GPIO: {e}")
    print("Please install RPi.GPIO: pip install RPi.GPIO")
    print("You may need to install system packages: sudo apt-get install python3-rpi.gpio")

print("\nTesting trilobot import...")
try:
    # Try to import the Trilobot library
    print("Importing trilobot module...")
    import trilobot
    print("Import successful!")
    print("Trilobot version:", getattr(trilobot, "__version__", "unknown"))
    
    from trilobot import Trilobot
    print("Trilobot class imported!")
    
    # Try to initialize the Trilobot
    print("\nInitializing Trilobot...")
    bot = Trilobot()
    print("Initialization successful!")
    
    # Simple LED test
    print("Running LED test (should see red, green, blue lights)...")
    bot.clear_underlighting()
    time.sleep(0.5)
    
    print("Red...")
    bot.fill_underlighting((255, 0, 0))
    time.sleep(1)
    
    print("Green...")
    bot.fill_underlighting((0, 255, 0))
    time.sleep(1)
    
    print("Blue...")
    bot.fill_underlighting((0, 0, 255))
    time.sleep(1)
    
    bot.clear_underlighting()
    print("LED test complete.")
    
    # Test distance sensor
    print("Testing distance sensor...")
    distance = bot.read_distance()
    print(f"Distance reading: {distance} cm")
    
    print("\nAll tests passed! Trilobot is working correctly.")
    
except ImportError as e:
    print(f"ERROR: Failed to import Trilobot library: {e}")
    print("Make sure trilobot is installed: pip install trilobot")
    traceback.print_exc()
    
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
    print("\nThis could be due to:")
    print("1. Trilobot HAT not properly connected")
    print("2. I2C not enabled (run: sudo raspi-config)")
    print("3. Permission issues (run with sudo or add user to i2c/gpio groups)")
    print("4. Conflicting software/hardware")
    
    print("\nTry these steps:")
    print("1. Install RPi.GPIO: sudo apt-get install python3-rpi.gpio")
    print("2. Install in virtual environment: pip install RPi.GPIO")
    print("3. Add your user to groups: sudo usermod -a -G gpio,i2c,spi <username>")
    print("4. Reboot the Pi: sudo reboot") 