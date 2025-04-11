#!/usr/bin/env python3
"""
Trilobot Diagnostic Tool

This script checks if the Trilobot hardware can be properly detected 
and accessed on your Raspberry Pi.
"""

import os
import sys
import time
import subprocess

def check_user():
    """Check if running as root/sudo"""
    print(f"Running as user: {os.getuid()}")
    if os.getuid() != 0:
        print("WARNING: Not running as root. This may cause permission issues.")
    else:
        print("Running as root - good!")
    
    # Check groups of current user
    username = subprocess.check_output("whoami", shell=True).decode().strip()
    groups = subprocess.check_output(f"groups {username}", shell=True).decode().strip()
    print(f"User groups: {groups}")
    
    for required_group in ['gpio', 'i2c', 'spi']:
        if required_group not in groups:
            print(f"WARNING: User not in {required_group} group. This may cause permission issues.")

def check_i2c():
    """Check if I2C is enabled and can be accessed"""
    print("\nChecking I2C...")
    
    try:
        # Check if I2C is enabled in raspi-config
        i2c_status = subprocess.check_output("raspi-config nonint get_i2c", shell=True).decode().strip()
        if i2c_status == "0":
            print("I2C is enabled in raspi-config - good!")
        else:
            print("WARNING: I2C is not enabled in raspi-config.")
            print("Enable it with: sudo raspi-config nonint do_i2c 0")
    except:
        print("Unable to check I2C status in raspi-config.")
    
    # Check for I2C devices
    try:
        i2c_devices = subprocess.check_output("ls -l /dev/i2c*", shell=True).decode().strip()
        print(f"I2C devices: {i2c_devices}")
    except:
        print("No I2C devices found in /dev/.")
        
    # Try to detect I2C devices with i2cdetect
    try:
        print("Detecting I2C devices...")
        i2cdetect = subprocess.check_output("i2cdetect -y 1", shell=True).decode().strip()
        print(i2cdetect)
    except:
        print("Unable to run i2cdetect. Install with: sudo apt-get install i2c-tools")

def check_gpio():
    """Check if GPIO can be accessed"""
    print("\nChecking GPIO...")
    
    try:
        # Check GPIO devices
        gpio_devices = subprocess.check_output("ls -l /dev/gpio*", shell=True).decode().strip()
        print(f"GPIO devices: {gpio_devices}")
    except:
        print("No GPIO devices found in /dev/. This may be normal.")
    
    # Check if GPIO can be accessed using gpiozero
    try:
        from gpiozero import LED
        print("Testing GPIO access with gpiozero...")
        led = LED(17)  # Using a standard GPIO pin
        print("GPIO access with gpiozero successful!")
    except ImportError:
        print("gpiozero library not installed.")
    except Exception as e:
        print(f"Error accessing GPIO: {e}")

def check_trilobot():
    """Attempt to initialize Trilobot and access its features"""
    print("\nChecking Trilobot library...")
    
    # Check if trilobot package is installed
    try:
        import pkg_resources
        version = pkg_resources.get_distribution("trilobot").version
        print(f"Trilobot library is installed (version {version}).")
    except:
        print("Trilobot library is not installed or cannot be found.")
        print("Install with: pip install trilobot")
        return
    
    # Try to import and initialize trilobot
    try:
        print("Attempting to initialize Trilobot...")
        from trilobot import Trilobot
        bot = Trilobot()
        print("Trilobot successfully initialized!")
        
        # Test LEDs
        print("Testing LEDs...")
        bot.clear_underlighting()
        time.sleep(0.5)
        
        print("Setting all LEDs to red...")
        bot.fill_underlighting((255, 0, 0))
        time.sleep(1)
        
        print("Setting all LEDs to green...")
        bot.fill_underlighting((0, 255, 0))
        time.sleep(1)
        
        print("Setting all LEDs to blue...")
        bot.fill_underlighting((0, 0, 255))
        time.sleep(1)
        
        bot.clear_underlighting()
        print("LED test complete.")
        
        # Test distance sensor
        try:
            print("\nTesting distance sensor...")
            distance = bot.read_distance()
            print(f"Distance reading: {distance} cm")
        except Exception as e:
            print(f"Error reading distance sensor: {e}")
            
    except ImportError:
        print("Failed to import Trilobot library.")
    except Exception as e:
        print(f"Error initializing Trilobot: {e}")
        print("This could be due to:")
        print("1. Trilobot hat not properly connected")
        print("2. I2C not properly enabled")
        print("3. Permission issues with hardware access")
        print("4. Conflicting libraries or hardware issues")

def print_system_info():
    """Print system information"""
    print("\nSystem Information:")
    try:
        # Get Raspberry Pi model
        model = subprocess.check_output("cat /proc/device-tree/model", shell=True).decode().strip()
        print(f"Model: {model}")
    except:
        print("Unable to determine Raspberry Pi model.")
    
    try:
        # Get OS information
        os_info = subprocess.check_output("cat /etc/os-release | grep PRETTY_NAME", shell=True).decode().strip()
        os_name = os_info.split('=')[1].strip('"')
        print(f"OS: {os_name}")
    except:
        print("Unable to determine OS version.")
    
    try:
        # Get kernel version
        kernel = subprocess.check_output("uname -r", shell=True).decode().strip()
        print(f"Kernel: {kernel}")
    except:
        print("Unable to determine kernel version.")
    
    try:
        # Get Python version
        python_version = sys.version.split()[0]
        print(f"Python: {python_version}")
    except:
        print("Unable to determine Python version.")

def main():
    """Main diagnostic function"""
    print("=== Trilobot Diagnostic Tool ===")
    print("Running diagnostics to check Trilobot hardware and configuration...")
    
    print_system_info()
    check_user()
    check_i2c()
    check_gpio()
    check_trilobot()
    
    print("\n=== Diagnostic Complete ===")
    print("If you're still having issues, check:")
    print("1. Make sure your Trilobot HAT is properly connected")
    print("2. Ensure I2C is enabled: sudo raspi-config → Interface Options → I2C → Yes")
    print("3. Add your user to required groups: sudo usermod -a -G gpio,i2c,spi <username>")
    print("4. Try the official Pimoroni tools: curl https://get.pimoroni.com/trilobot | bash")

if __name__ == "__main__":
    main() 