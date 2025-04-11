#!/usr/bin/env python3
"""
Test script to check hardware components individually
"""

import sys
import time
import subprocess
import os
import logging

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_hardware')

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

def test_trilobot():
    """Test if Trilobot library is available"""
    print("\n=== TESTING TRILOBOT LIBRARY ===")
    try:
        print("Checking for Trilobot module...")
        import trilobot
        print(f"✓ Trilobot module found")
        
        # Try to initialize Trilobot
        try:
            from trilobot import Trilobot
            bot = Trilobot()
            print("✓ Trilobot initialized successfully")
            return True
        except Exception as e:
            print(f"✗ Trilobot initialization error: {e}")
            print("  This might be expected if running on development machine")
            return False
    except ImportError:
        print("✗ Trilobot module not found")
        print("  Follow installation instructions at: https://github.com/pimoroni/trilobot-python")
        return False
    except Exception as e:
        print(f"✗ Trilobot test error: {e}")
        return False

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
    """Run all hardware tests"""
    print("=== TRILOBOT HARDWARE TEST ===")
    print(f"Python version: {sys.version}")
    print(f"System platform: {sys.platform}")
    print(f"Current directory: {os.getcwd()}")
    print("Running tests...\n")
    
    # Run all tests
    camera_ok = test_camera()
    bluetooth_ok = test_bluetooth()
    controller_ok = test_controller()
    flask_ok = test_flask()
    trilobot_ok = test_trilobot()
    network_ok = network_check()
    
    # Print summary
    print("\n=== TEST SUMMARY ===")
    print(f"Camera:     {'✓ OK' if camera_ok else '✗ FAILED'}")
    print(f"Bluetooth:  {'✓ OK' if bluetooth_ok else '✗ FAILED'}")
    print(f"Controller: {'✓ OK' if controller_ok else '✗ FAILED'}")
    print(f"Web Server: {'✓ OK' if flask_ok else '✗ FAILED'}")
    print(f"Trilobot:   {'✓ OK' if trilobot_ok else '✗ FAILED'}")
    print(f"Network:    {'✓ OK' if network_ok else '✗ FAILED'}")
    
    # Final assessment
    total_tests = 6
    passed_tests = sum([camera_ok, bluetooth_ok, controller_ok, flask_ok, trilobot_ok, network_ok])
    
    print(f"\nTests passed: {passed_tests}/{total_tests}")
    
    essential_tests = [flask_ok, trilobot_ok]
    if all(essential_tests) and (camera_ok or controller_ok or network_ok):
        print("\n✓ Basic functionality should work!")
        if not camera_ok:
            print("  ⚠️ Camera not working - web interface will use placeholder images")
        if not controller_ok:
            print("  ⚠️ PS4 controller not working - only web controls will be available")
        return True
    else:
        print("\n✗ Some essential components are not working")
        print("  Please fix the failed tests before continuing")
        return False

if __name__ == "__main__":
    main() 