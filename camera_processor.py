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
import numpy as np
from datetime import datetime

# Import local modules
from debugging import log_info, log_error, log_warning, Performance
from config import config

logger = logging.getLogger('trilobot.camera')

# Try to import hardware-specific modules
try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    hardware_available = True
except ImportError:
    hardware_available = False
    logger.warning("Camera hardware modules not available. Using mock objects.")

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
        self.overlay_mode = 'normal'
        self.running = False
        self.detection_enabled = False  # Object detection disabled (removed OpenCV dependency)
        
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
            resolution = config.get("camera", "resolution")
            framerate = config.get("camera", "framerate")
            
            self.camera = Picamera2()
            camera_config = self.camera.create_video_configuration(
                main={"size": (resolution[0], resolution[1])},
                encode="main",
                buffer_count=4
            )
            self.camera.configure(camera_config)
            log_info("Camera initialized successfully")
        except Exception as e:
            log_error(f"Camera initialization error: {e}")
            self.camera = None
    
    def start(self):
        """Start camera and processing"""
        if self.running:
            log_warning("Camera processor already running")
            return False
            
        if not hardware_available:
            log_warning("Hardware not available. Cannot start camera.")
            return False
            
        try:
            # Start camera recording
            encoder = MJPEGEncoder(bitrate=8000000)
            self.camera.start_recording(encoder, FileOutput(self.output))
            
            self.running = True
            log_info("Camera processor started")
            return True
        except Exception as e:
            log_error(f"Error starting camera processor: {e}")
            return False
    
    def stop(self):
        """Stop camera and processing"""
        if not self.running:
            return
            
        try:
            # Stop camera
            if self.camera:
                self.camera.stop_recording()
                
            self.running = False
            log_info("Camera processor stopped")
        except Exception as e:
            log_error(f"Error stopping camera processor: {e}")
    
    def set_overlay_mode(self, mode):
        """Set the overlay mode for camera stream"""
        self.overlay_mode = mode
        log_info(f"Camera overlay mode set to: {mode}")
    
    def take_photo(self):
        """Capture a still photo"""
        if not hardware_available or not self.camera:
            log_warning("Hardware not available. Cannot take photo.")
            return None
            
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(self.capture_dir, f"photo_{timestamp}.jpg")
            
            # Capture image
            self.camera.stop_recording()
            
            # Capture and save directly to file
            self.camera.capture_file(filepath)
            
            # Restart recording
            encoder = MJPEGEncoder(bitrate=8000000)
            self.camera.start_recording(encoder, FileOutput(self.output))
            
            log_info(f"Photo captured: {filepath}")
            return filepath
        except Exception as e:
            log_error(f"Error taking photo: {e}")
            
            # Try to restart recording if it failed
            try:
                encoder = MJPEGEncoder(bitrate=8000000)
                self.camera.start_recording(encoder, FileOutput(self.output))
            except:
                pass
                
            return None
    
    def get_stream(self):
        """Get the camera stream output"""
        return self.output
    
    def get_detected_objects(self):
        """Get the latest detected objects (empty list - detection removed)"""
        return []
    
    def apply_overlay(self, frame):
        """Apply the current overlay mode to a frame (simplified without OpenCV)"""
        # Simply return the original frame since we've removed OpenCV processing capabilities
        return frame

# Create global camera processor instance
camera_processor = CameraProcessor() 