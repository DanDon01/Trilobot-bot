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
from debugging import log_info, log_error, log_warning, Performance, safe_log
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
    safe_log(logger, 'info', "Camera hardware detected and available")
except ImportError as e:
    picamera2_error = f"PiCamera2 module not found: {e}"
    safe_log(logger, 'warning', f"Camera hardware modules not available: {picamera2_error}")
    safe_log(logger, 'warning', "Make sure picamera2 is installed: sudo apt-get install -y python3-picamera2")
except Exception as e:
    picamera2_error = f"Camera hardware error: {e}"
    safe_log(logger, 'warning', f"Camera hardware error: {picamera2_error}")
    safe_log(logger, 'warning', "Make sure the camera is enabled with 'sudo raspi-config' and connected properly")
if not hardware_available:
    from camera_cv import camera_processor   # <- tiny OpenCV backend
else:
    camera_processor = CameraProcessor()


# Use numpy only if it's available, otherwise create a simple mock implementation
try:
    import numpy as np
except ImportError:
    safe_log(logger, 'warning', "NumPy not available, using simplified implementation")
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
        """Capture a still photo by saving the current frame from the stream"""
        try:
            # Use absolute paths
            script_dir = os.path.dirname(os.path.abspath(__file__))
            capture_dir_abs = os.path.join(script_dir, self.capture_dir)
            
            # Create captures directory if it doesn't exist
            if not os.path.exists(capture_dir_abs):
                log_info(f"Creating capture directory at: {capture_dir_abs}")
                os.makedirs(capture_dir_abs, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(capture_dir_abs, f"photo_{timestamp}.jpg")
            log_info(f"Taking photo and saving to: {filepath}")
            
            # Check if we have a valid output stream
            if not self.output or not hasattr(self.output, 'frame') or self.output.frame is None:
                log_error("Cannot take photo: No active video stream or frame available")
                return None
                
            # Get current frame directly from the stream
            current_frame = self.output.frame
            if not current_frame:
                log_error("Cannot take photo: Current frame is empty")
                return None
                
            # Save the frame directly to file
            try:
                with open(filepath, 'wb') as f:
                    f.write(current_frame)
                
                # Verify file was saved
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    file_size = os.path.getsize(filepath)
                    log_info(f"Photo saved successfully: {filepath} ({file_size} bytes)")
                    # Change permissions to ensure it's readable
                    try:
                        os.chmod(filepath, 0o666)  # Make readable/writable by everyone
                    except Exception as perm_e:
                        log_warning(f"Could not set file permissions: {perm_e}")
                    return filepath
                else:
                    log_error(f"Photo file was not created or is empty: {filepath}")
                    return None
            except Exception as save_error:
                log_error(f"Error saving photo: {save_error}")
                import traceback
                log_error(f"Save error traceback: {traceback.format_exc()}")
                return None
                
        except Exception as e:
            log_error(f"Error in take_photo: {e}")
            import traceback
            log_error(f"Error traceback: {traceback.format_exc()}")
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