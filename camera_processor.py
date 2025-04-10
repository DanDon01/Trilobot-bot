"""
Camera Processor Module for Trilobot

This module handles camera functionality including streaming,
basic image processing, and computer vision capabilities.
"""

import threading
import time
import os
import logging
import io
from threading import Condition
import cv2
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

# Try to import TensorFlow Lite for object detection
try:
    import tflite_runtime.interpreter as tflite
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False
    logger.warning("TensorFlow Lite not available. Object detection disabled.")

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
        self.detection_enabled = config.get("vision", "enabled") and TENSORFLOW_AVAILABLE
        
        # Object detection properties
        self.interpreter = None
        self.detected_objects = []
        self.detection_thread = None
        self.stop_detection = threading.Event()
        
        # Paths for captures
        self.capture_dir = "captures"
        if not os.path.exists(self.capture_dir):
            os.makedirs(self.capture_dir)
        
        # Initialize camera if hardware available
        if hardware_available:
            self._init_camera()
            
        # Initialize object detection if enabled
        if self.detection_enabled:
            self._init_object_detection()
        
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
    
    def _init_object_detection(self):
        """Initialize TensorFlow Lite object detection"""
        if not TENSORFLOW_AVAILABLE:
            log_warning("TensorFlow Lite not available. Object detection disabled.")
            return False
            
        try:
            model_path = config.get("vision", "model_path")
            if not os.path.exists(model_path):
                log_error(f"Model file not found: {model_path}")
                return False
                
            self.interpreter = tflite.Interpreter(model_path=model_path)
            self.interpreter.allocate_tensors()
            log_info("Object detection model loaded successfully")
            return True
        except Exception as e:
            log_error(f"Object detection initialization error: {e}")
            return False
    
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
            
            # Start object detection if enabled
            if self.detection_enabled:
                self.stop_detection.clear()
                self.detection_thread = threading.Thread(target=self._detection_loop)
                self.detection_thread.daemon = True
                self.detection_thread.start()
            
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
            # Stop object detection
            if self.detection_thread and self.detection_thread.is_alive():
                self.stop_detection.set()
                self.detection_thread.join(timeout=1.0)
            
            # Stop camera
            if self.camera:
                self.camera.stop_recording()
                self.camera.close()
            
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
            array = self.camera.capture_array()
            image = cv2.cvtColor(array, cv2.COLOR_YUV420p2RGB)
            cv2.imwrite(filepath, image)
            
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
    
    @Performance.timed
    def _detection_loop(self):
        """Object detection processing loop"""
        log_info("Starting object detection loop")
        
        # Get detection interval from config
        detection_interval = config.get("vision", "detection_interval")
        confidence_threshold = config.get("vision", "confidence_threshold")
        
        while not self.stop_detection.is_set():
            try:
                # Get current frame
                with self.output.condition:
                    if self.output.frame is None:
                        self.output.condition.wait()
                    frame = self.output.frame
                
                if frame is None:
                    continue
                    
                # Convert JPEG to array
                array = np.frombuffer(frame, dtype=np.uint8)
                img = cv2.imdecode(array, cv2.IMREAD_COLOR)
                
                # Process frame with TensorFlow Lite
                input_details = self.interpreter.get_input_details()
                output_details = self.interpreter.get_output_details()
                
                # Resize and normalize image
                height = input_details[0]['shape'][1]
                width = input_details[0]['shape'][2]
                input_data = cv2.resize(img, (width, height))
                input_data = np.expand_dims(input_data, axis=0)
                
                # Run detection
                self.interpreter.set_tensor(input_details[0]['index'], input_data)
                self.interpreter.invoke()
                
                # Get results
                boxes = self.interpreter.get_tensor(output_details[0]['index'])[0]
                classes = self.interpreter.get_tensor(output_details[1]['index'])[0]
                scores = self.interpreter.get_tensor(output_details[2]['index'])[0]
                
                # Filter and store results
                detected = []
                for i in range(len(scores)):
                    if scores[i] >= confidence_threshold:
                        detected.append({
                            'class': int(classes[i]),
                            'score': float(scores[i]),
                            'box': boxes[i].tolist()
                        })
                
                # Update detected objects
                self.detected_objects = detected
                
            except Exception as e:
                log_error(f"Error in object detection: {e}")
            
            # Sleep for detection interval
            time.sleep(detection_interval)
    
    def get_stream(self):
        """Get the camera stream output"""
        return self.output
    
    def get_detected_objects(self):
        """Get the latest detected objects"""
        return self.detected_objects
    
    def apply_overlay(self, frame):
        """Apply the current overlay mode to a frame"""
        if not frame:
            return frame
            
        try:
            # Convert JPEG to array for processing
            array = np.frombuffer(frame, dtype=np.uint8)
            img = cv2.imdecode(array, cv2.IMREAD_COLOR)
            
            if self.overlay_mode == 'night_vision':
                # Convert to grayscale then apply green tint
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                img[:,:,0] = 0  # Zero out blue channel
                img[:,:,2] = 0  # Zero out red channel
                
            elif self.overlay_mode == 'targeting':
                # Draw targeting overlay
                height, width = img.shape[:2]
                center_x, center_y = width // 2, height // 2
                
                # Draw crosshair
                cv2.line(img, (center_x, 0), (center_x, height), (0, 0, 255), 1)
                cv2.line(img, (0, center_y), (width, center_y), (0, 0, 255), 1)
                
                # Draw circles
                cv2.circle(img, (center_x, center_y), 50, (0, 0, 255), 1)
                cv2.circle(img, (center_x, center_y), 100, (0, 0, 255), 1)
                
            # Draw detected objects if available
            if self.detection_enabled and self.detected_objects:
                height, width = img.shape[:2]
                for obj in self.detected_objects:
                    # Convert normalized coordinates to pixel coordinates
                    ymin, xmin, ymax, xmax = obj['box']
                    xmin = int(xmin * width)
                    xmax = int(xmax * width)
                    ymin = int(ymin * height)
                    ymax = int(ymax * height)
                    
                    # Draw bounding box
                    cv2.rectangle(img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                    
                    # Draw label
                    label = f"Class {obj['class']}: {obj['score']:.2f}"
                    cv2.putText(img, label, (xmin, ymin - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # Convert back to JPEG
            _, processed_frame = cv2.imencode('.jpg', img)
            return processed_frame.tobytes()
            
        except Exception as e:
            log_error(f"Error applying overlay: {e}")
            return frame

# Create global camera processor instance
camera_processor = CameraProcessor() 