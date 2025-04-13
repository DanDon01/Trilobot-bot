"""
Camera Processor Module for Trilobot

This module handles camera functionality including streaming,
basic image processing, and camera capabilities.
"""

import threading
import time
import os
import logging
import io
from threading import Condition
import sys
from datetime import datetime

# Import local modules
from debugging import log_info, log_error, log_warning, Performance
from config import config

logger = logging.getLogger('trilobot.camera')

# Try to import hardware-specific modules
hardware_available = False
picamera2_error = None

try:
    # First try to import the required modules
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    
    # Then verify if the camera is actually accessible
    # This will raise an exception if no camera is found
    test_camera = Picamera2()
    test_camera.close()
    
    hardware_available = True
    log_info("Camera hardware detected and available")
except ImportError as e:
    picamera2_error = f"PiCamera2 module not found: {e}"
    log_warning(f"Camera hardware modules not available: {picamera2_error}")
    log_warning("Make sure picamera2 is installed: sudo apt-get install -y python3-picamera2")
except Exception as e:
    picamera2_error = f"Camera hardware error: {e}"
    log_warning(f"Camera hardware error: {picamera2_error}")
    log_warning("Make sure the camera is enabled with 'sudo raspi-config' and connected properly")

# Use numpy only if it's available, otherwise create a simple mock implementation
try:
    import numpy as np
except ImportError:
    log_warning("NumPy not available, using simplified implementation")
    class MockNumpy:
        pass
    np = MockNumpy()

class StreamingOutput(io.BufferedIOBase):
    """Output stream for camera data"""
    def __init__(self):
        self.frame = None
        self.processed_frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class CameraProcessor:
    """Manager for camera operations and processing"""
    
    def __init__(self):
        self.camera = None
        self.output = StreamingOutput()
        self.processing_output = StreamingOutput()
        self.running = False
        self.detection_enabled = False
        self.hardware_error = picamera2_error
        
        # Paths for captures
        self.capture_dir = "captures"
        if not os.path.exists(self.capture_dir):
            os.makedirs(self.capture_dir)
        
        # Initialize camera if hardware available
        if hardware_available:
            self._init_camera()
        
        log_info("Camera Processor initialized")
    
    def _init_camera(self):
        """Initialize the camera hardware"""
        try:
            # Use lower resolution to avoid memory allocation errors
            # Original resolution from config may be too high
            resolution = (640, 480)  # Low resolution that should work reliably
            framerate = config.get("camera", "framerate")
            
            # Detailed logging to diagnose issues
            log_info(f"Initializing camera with resolution {resolution}, framerate {framerate}")
            
            self.camera = Picamera2()
            
            # Set a lower buffer count to reduce memory usage
            camera_config = self.camera.create_video_configuration(
                main={"size": (resolution[0], resolution[1])},
                encode="main",
                buffer_count=2  # Reduced from 4 to lower memory usage
            )
            self.camera.configure(camera_config)
            
            # Test that we can get camera info
            camera_info = self.camera.camera_properties
            log_info(f"Camera initialized successfully. Camera info: {camera_info}")
            
            return True
        except Exception as e:
            error_msg = f"Camera initialization error: {str(e)}"
            log_error(error_msg)
            self.hardware_error = error_msg
            self.camera = None
            return False
    
    def start(self):
        """Start camera and processing"""
        if self.running:
            log_warning("Camera processor already running")
            return False
            
        if not hardware_available:
            log_warning(f"Hardware not available. Cannot start camera. Error: {self.hardware_error}")
            return False
            
        try:
            # Start camera recording
            log_info("Starting camera recording...")
            encoder = MJPEGEncoder(bitrate=8000000)
            self.camera.start_recording(encoder, FileOutput(self.output))
            
            self.running = True
            log_info("Camera processor started successfully")
            return True
        except Exception as e:
            error_msg = f"Error starting camera processor: {str(e)}"
            log_error(error_msg)
            self.hardware_error = error_msg
            return False
    
    def stop(self):
        """Stop camera and processing"""
        if not self.running:
            return
            
        try:
            # Stop camera
            if self.camera:
                log_info("Stopping camera recording...")
                self.camera.stop_recording()
                
            self.running = False
            log_info("Camera processor stopped")
        except Exception as e:
            log_error(f"Error stopping camera processor: {e}")
    
    def take_photo(self):
        """Capture a still photo"""
        if not hardware_available or not self.camera:
            log_warning(f"Hardware not available. Cannot take photo. Error: {self.hardware_error}")
            return None
            
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(self.capture_dir, f"photo_{timestamp}.jpg")
            
            # More detailed logging
            log_info(f"Photo capture requested. Path: {filepath}")
            log_info(f"Capture directory exists: {os.path.exists(self.capture_dir)}")
            
            # Ensure the capture directory is accessible
            if not os.path.exists(self.capture_dir):
                log_info(f"Creating capture directory: {self.capture_dir}")
                os.makedirs(self.capture_dir, exist_ok=True)
            
            # Capture image
            log_info("Stopping recording to take photo...")
            was_recording = self.running
            if was_recording:
                self.camera.stop_recording()
            
            # Capture and save directly to file
            log_info(f"Capturing photo to {filepath}...")
            self.camera.capture_file(filepath)
            
            # Verify file was created
            if os.path.exists(filepath):
                log_info(f"Photo file successfully created: {os.path.getsize(filepath)} bytes")
            else:
                log_error(f"Photo file was not created at {filepath}")
            
            # Restart recording if it was recording before
            if was_recording:
                log_info("Restarting recording...")
                try:
                    encoder = MJPEGEncoder(bitrate=8000000)
                    self.camera.start_recording(encoder, FileOutput(self.output))
                    self.running = True
                except Exception as restart_error:
                    log_error(f"Failed to restart recording: {restart_error}")
                    self.running = False
            
            log_info(f"Photo captured: {filepath}")
            return filepath
        except Exception as e:
            error_msg = f"Error taking photo: {str(e)}"
            log_error(error_msg)
            # Log stack trace for debugging
            import traceback
            log_error(f"Photo capture error stack trace: {traceback.format_exc()}")
            
            # Try to restart recording if it failed
            try:
                log_info("Attempting to restart recording after error...")
                encoder = MJPEGEncoder(bitrate=8000000)
                self.camera.start_recording(encoder, FileOutput(self.output))
                self.running = True
            except Exception as restart_error:
                log_error(f"Failed to restart recording: {restart_error}")
                self.running = False
                
            return None
    
    def get_stream(self):
        """Get the camera stream output"""
        return self.output
    
    def get_detected_objects(self):
        """Get the latest detected objects (empty list - detection removed)"""
        return []
    
    def get_camera_status(self):
        """Get the current status of the camera"""
        return {
            "available": hardware_available,
            "running": self.running,
            "error": self.hardware_error
        }

# Create global camera processor instance
camera_processor = CameraProcessor() 