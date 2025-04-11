#!/usr/bin/env python3
"""
Trilobot Hardware Test Script

This script attempts to locate and test the Trilobot hardware.
It will display detailed information to help troubleshoot hardware issues.
"""

import sys
import time
import subprocess
import os
import logging
import importlib

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_hardware')

# Define colored output for better readability
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_section(title):
    """Print a section header"""
    print(f"\n{BLUE}{'=' * 40}{RESET}")
    print(f"{BLUE}{title.center(40)}{RESET}")
    print(f"{BLUE}{'=' * 40}{RESET}\n")

def print_success(message):
    """Print a success message"""
    print(f"{GREEN}✓ {message}{RESET}")

def print_warning(message):
    """Print a warning message"""
    print(f"{YELLOW}! {message}{RESET}")

def print_error(message):
    """Print an error message"""
    print(f"{RED}✗ {message}{RESET}")

def print_info(message):
    """Print an info message"""
    print(f"  {message}")

def test_camera():
    """Test if the camera is working properly"""
    print("\n=== TESTING CAMERA ===")
    try:
        print("Checking if picamera2 is installed...")
        import picamera2
        print("✓ picamera2 module found")
        
        print("Trying to initialize camera...")
        from picamera2 import Picamera2
        try:
            camera = Picamera2()
            print("✓ Camera initialized")
            
            # Check if camera is physically connected
            try:
                camera_info = camera.camera_properties
                print(f"✓ Camera properties: {camera_info}")
                
                print("Taking a test photo...")
                # Create basic configuration
                config = camera.create_still_configuration()
                camera.configure(config)
                camera.start()
                
                # Capture a test image
                test_file = "test_photo.jpg"
                camera.capture_file(test_file)
                print(f"✓ Test photo saved to {test_file}")
                
                # Clean up
                camera.close()
                return True
            except Exception as e:
                print(f"✗ Camera hardware error: {e}")
                print("  Make sure the camera ribbon cable is properly connected")
                print("  and that the camera is enabled in raspi-config")
                return False
        except Exception as e:
            print(f"✗ Camera initialization error: {e}")
            return False
    except ImportError:
        print("✗ picamera2 module not found")
        print("  Run: sudo apt-get install -y python3-picamera2 python3-libcamera")
        return False

def test_bluetooth():
    """Test if Bluetooth is working properly"""
    print("\n=== TESTING BLUETOOTH ===")
    try:
        print("Checking if bluetooth service is running...")
        result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                                capture_output=True, text=True)
        
        if result.stdout.strip() == 'active':
            print("✓ Bluetooth service is active")
            
            # Check for bluetoothctl
            print("Testing bluetoothctl...")
            bt_result = subprocess.run(['bluetoothctl', 'show'], 
                                    capture_output=True, text=True, timeout=2)
            
            if "No default controller available" in bt_result.stdout:
                print("✗ No Bluetooth controller found")
                print("  Make sure Bluetooth hardware is available and enabled")
                return False
            
            print("✓ Bluetooth controller is available")
            
            # List paired devices
            print("Checking paired devices...")
            devices_result = subprocess.run(['bluetoothctl', 'devices'], 
                                        capture_output=True, text=True)
            
            devices = devices_result.stdout.strip().split('\n')
            devices = [d for d in devices if d.strip()]
            
            if devices:
                print(f"✓ Found {len(devices)} paired device(s):")
                for device in devices:
                    print(f"  - {device}")
            else:
                print("No paired devices found")
                
            return True
        else:
            print(f"✗ Bluetooth service is not active (status: {result.stdout.strip()})")
            print("  Run: sudo systemctl start bluetooth")
            return False
    except FileNotFoundError:
        print("✗ bluetoothctl command not found")
        print("  Run: sudo apt-get install -y bluetooth pi-bluetooth")
        return False
    except Exception as e:
        print(f"✗ Bluetooth test error: {e}")
        return False

def test_controller():
    """Test if PS4 controller can be detected"""
    print("\n=== TESTING PS4 CONTROLLER ===")
    try:
        print("Checking for evdev module...")
        try:
            import evdev
            print("✓ evdev module found")
            
            print("Looking for input devices...")
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            
            if devices:
                print(f"✓ Found {len(devices)} input device(s):")
                for device in devices:
                    print(f"  - {device.name} (path: {device.path})")
                
                ps4_devices = [d for d in devices if 
                              'sony' in d.name.lower() or 
                              'playstation' in d.name.lower() or 
                              'wireless controller' in d.name.lower() or 
                              'dualshock' in d.name.lower()]
                
                if ps4_devices:
                    print(f"✓ Found PS4 controller: {ps4_devices[0].name}")
                    return True
                else:
                    print("✗ No PS4 controller found among input devices")
                    print("  Make sure your controller is paired with Bluetooth")
                    print("  You might need to put your controller in pairing mode:")
                    print("  - Press and hold SHARE + PS button until light bar flashes")
                    return False
            else:
                print("✗ No input devices found")
                print("  Run: sudo apt-get install -y joystick")
                return False
        except ImportError:
            print("✗ evdev module not found")
            print("  Run: sudo apt-get install -y python3-evdev")
            return False
    except Exception as e:
        print(f"✗ Controller test error: {e}")
        return False

def test_flask():
    """Test if Flask web server can be initialized"""
    print("\n=== TESTING WEB SERVER ===")
    try:
        print("Checking for Flask module...")
        import flask
        print(f"✓ Flask module found (version {flask.__version__})")
        return True
    except ImportError:
        print("✗ Flask module not found")
        print("  Run: pip install flask")
        return False
    except Exception as e:
        print(f"✗ Flask test error: {e}")
        return False

def check_python_environment():
    """Check Python environment information"""
    print_section("PYTHON ENVIRONMENT")
    print_info(f"Python version: {sys.version}")
    print_info(f"Python executable: {sys.executable}")
    print_info(f"Platform: {sys.platform}")
    
    # Check sys.path
    print_info("\nPython module search paths:")
    for i, path in enumerate(sys.path):
        if os.path.exists(path):
            print_info(f"  {i+1}. {path} [EXISTS]")
        else:
            print_info(f"  {i+1}. {path} [MISSING]")

def check_trilobot_library():
    """Check for Trilobot library"""
    print_section("TRILOBOT LIBRARY CHECK")
    
    # Try different methods to find the library
    try:
        import trilobot
        print_success(f"Trilobot library found at: {trilobot.__file__}")
        
        # Check version if available
        if hasattr(trilobot, "__version__"):
            print_info(f"Trilobot library version: {trilobot.__version__}")
    except ImportError as e:
        print_error(f"Failed to import trilobot: {e}")
        
        # Check if the library is installed using pip
        print_info("\nChecking installed packages...")
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', 'list'], 
                                   capture_output=True, text=True)
            if 'trilobot' in result.stdout:
                print_warning("Trilobot appears in pip list but cannot be imported")
                # Extract version from pip list
                for line in result.stdout.split('\n'):
                    if 'trilobot' in line:
                        print_info(f"  {line.strip()}")
            else:
                print_error("Trilobot not found in pip list")
                print_info("  Try installing with: sudo pip3 install trilobot")
        except Exception as e:
            print_error(f"Error checking pip list: {e}")
        
        # Try to find the library in common locations
        potential_paths = [
            os.path.expanduser('~/Pimoroni/trilobot/library'),
            '/usr/local/lib/python3.9/dist-packages',
            '/usr/local/lib/python3.7/dist-packages',
            '/usr/local/lib/python3/dist-packages',
            '/usr/lib/python3/dist-packages',
        ]
        
        print_info("\nChecking potential library locations...")
        for path in potential_paths:
            trilobot_path = os.path.join(path, "trilobot.py")
            if os.path.exists(trilobot_path):
                print_warning(f"Found trilobot.py at {trilobot_path}")
                print_info("  But it cannot be imported with the current Python environment")
        
        return False
    
    return True

def test_trilobot_hardware():
    """Test Trilobot hardware functionality"""
    print_section("TRILOBOT HARDWARE TEST")
    
    try:
        from trilobot import Trilobot
        print_success("Trilobot class imported successfully")
        
        # Try to initialize the hardware
        try:
            print_info("Initializing Trilobot hardware...")
            bot = Trilobot()
            print_success("Hardware initialized successfully")
            
            # Basic hardware tests
            print_info("\nRunning basic hardware tests...")
            
            # Test motors
            print_info("Testing motors (2 seconds each)...")
            
            # Forward
            print_info("  Forward...")
            bot.set_left_speed(0.5)
            bot.set_right_speed(0.5)
            time.sleep(2)
            
            # Stop
            bot.disable_motors()
            print_info("  Motors stopped")
            time.sleep(1)
            
            # Test lights
            print_info("Testing underlighting...")
            bot.fill_underlighting(255, 0, 0)  # Red
            time.sleep(1)
            bot.fill_underlighting(0, 255, 0)  # Green
            time.sleep(1)
            bot.fill_underlighting(0, 0, 255)  # Blue
            time.sleep(1)
            bot.clear_underlighting()
            print_info("  Underlighting test complete")
            
            print_success("All hardware tests completed successfully")
            
        except Exception as e:
            print_error(f"Error initializing or testing hardware: {e}")
            print_warning("This may indicate a hardware connection issue or permission problem")
            print_info("  Try running with sudo if this is a permission issue")
            return False
        
    except Exception as e:
        print_error(f"Error importing Trilobot class: {e}")
        return False
    
    return True

def network_check():
    """Check network connectivity"""
    print("\n=== TESTING NETWORK ===")
    try:
        # Get IP address
        print("Checking network interfaces...")
        ip_cmd = "hostname -I"
        ip_result = subprocess.run(ip_cmd.split(), capture_output=True, text=True)
        ip_addresses = ip_result.stdout.strip().split()
        
        if ip_addresses:
            print(f"✓ IP Addresses: {', '.join(ip_addresses)}")
        else:
            print("✗ No IP addresses found")
            print("  Check network configuration")
        
        # Test internet connectivity
        print("Testing internet connectivity...")
        ping_result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "8.8.8.8"], 
            capture_output=True, 
            text=True
        )
        
        if ping_result.returncode == 0:
            print("✓ Internet connection is available")
            return True
        else:
            print("✗ No internet connection")
            print("  This may be expected if running offline")
            return False
    except Exception as e:
        print(f"✗ Network test error: {e}")
        return False

def main():
    """Main function"""
    print_section("TRILOBOT HARDWARE DIAGNOSTIC")
    print_info("This script will check for the Trilobot library and test the hardware")
    print_info("Running tests...")
    
    # Run checks
    check_python_environment()
    lib_available = check_trilobot_library()
    
    if lib_available:
        hardware_ok = test_trilobot_hardware()
        
        if hardware_ok:
            print_section("SUMMARY")
            print_success("Trilobot library and hardware are working correctly")
            print_info("You should be able to run the main application now")
        else:
            print_section("SUMMARY")
            print_warning("Trilobot library is installed but hardware test failed")
            print_info("Check connections and permissions before running the main application")
    else:
        print_section("SUMMARY")
        print_error("Trilobot library could not be imported")
        print_info("Install the library before running the main application:")
        print_info("  sudo pip3 install trilobot")
        print_info("  or")
        print_info("  curl -sSL https://get.pimoroni.com/trilobot | bash")

if __name__ == "__main__":
    main() 