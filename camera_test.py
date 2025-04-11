#!/usr/bin/env python3
"""
Camera Test Script for Raspberry Pi

This script provides basic camera testing capabilities to diagnose
issues with the camera hardware on Raspberry Pi.
"""

import sys
import os
import time
from datetime import datetime

print("Camera Test Script for Raspberry Pi")
print("-----------------------------------")
print(f"Python version: {sys.version}")
print(f"System platform: {sys.platform}")
print()

# Check for the necessary modules
print("Checking for required modules:")

# Test for picamera2
try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder, H264Encoder
    from picamera2.outputs import FileOutput, FfmpegOutput
    print("✓ PiCamera2 module found")
    picamera2_available = True
except ImportError as e:
    print(f"✗ PiCamera2 module not found: {e}")
    print("  To install: sudo apt-get install -y python3-picamera2")
    picamera2_available = False
    
# If PiCamera2 is not available, check for legacy picamera
if not picamera2_available:
    try:
        import picamera
        print("✓ Legacy PiCamera module found (older version)")
        picamera_available = True
    except ImportError as e:
        print(f"✗ Legacy PiCamera module not found: {e}")
        print("  To install: sudo apt-get install -y python3-picamera")
        picamera_available = False
else:
    picamera_available = False

print()

# Check if camera is enabled in config
print("Checking Raspberry Pi camera configuration:")
try:
    import subprocess
    result = subprocess.run(['vcgencmd', 'get_camera'], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Camera config: {result.stdout.strip()}")
        if "detected=1" not in result.stdout:
            print("✗ Camera not detected in hardware configuration")
            print("  Make sure the camera is properly connected")
        else:
            print("✓ Camera detected in hardware configuration")
    else:
        print(f"✗ Error checking camera config: {result.stderr}")
except Exception as e:
    print(f"✗ Could not check camera configuration: {e}")

print()

# Attempt to initialize the camera
print("Attempting to initialize camera:")

if picamera2_available:
    try:
        camera = Picamera2()
        camera_info = camera.camera_properties
        print(f"✓ Camera initialized successfully")
        print(f"Camera properties: {camera_info}")
        
        # Try to capture a test image
        print("\nTaking a test photo...")
        config = camera.create_still_configuration()
        camera.configure(config)
        camera.start()
        
        # Create a timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"camera_test_{timestamp}.jpg"
        
        # Capture the image
        camera.capture_file(filename)
        print(f"✓ Test photo saved to: {filename}")
        
        # Try to record a short video
        print("\nRecording a test video (5 seconds)...")
        video_config = camera.create_video_configuration()
        camera.configure(video_config)
        
        video_filename = f"camera_test_{timestamp}.mp4"
        encoder = H264Encoder()
        output = FfmpegOutput(video_filename)
        
        camera.start_recording(encoder, output)
        print("Recording... (5 seconds)")
        time.sleep(5)
        camera.stop_recording()
        print(f"✓ Test video saved to: {video_filename}")
        
        camera.close()
        
    except Exception as e:
        print(f"✗ Camera initialization error: {e}")
        print("  This indicates a problem with the camera hardware or drivers")
elif picamera_available:
    try:
        camera = picamera.PiCamera()
        print(f"✓ Legacy PiCamera initialized successfully")
        
        # Try to capture a test image
        print("\nTaking a test photo...")
        
        # Create a timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"camera_test_{timestamp}.jpg"
        
        # Capture the image
        camera.capture(filename)
        print(f"✓ Test photo saved to: {filename}")
        
        # Try to record a short video
        print("\nRecording a test video (5 seconds)...")
        video_filename = f"camera_test_{timestamp}.h264"
        camera.start_recording(video_filename)
        print("Recording... (5 seconds)")
        time.sleep(5)
        camera.stop_recording()
        print(f"✓ Test video saved to: {video_filename}")
        
        camera.close()
        
    except Exception as e:
        print(f"✗ Camera initialization error: {e}")
        print("  This indicates a problem with the camera hardware or drivers")
else:
    print("✗ No camera modules available")
    print("  Please install picamera2 or picamera to test the camera")

print("\nCamera test complete.")
print("If you see any error messages above, please address those issues.")
print("If all tests passed, the camera should work with the main application.") 