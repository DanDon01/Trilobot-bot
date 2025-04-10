"""
Main Module for Trilobot

This is the main entry point for the Trilobot application.
It initializes all components and starts the necessary services.
"""

import time
import signal
import sys
import os
import threading
import logging

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker
from config import config
from control_manager import control_manager
from web_control import app as flask_app
from camera_processor import camera_processor
from voice_controller import voice_controller
from ps4_controller import ps4_controller

logger = logging.getLogger('trilobot.main')

# Global flag for graceful shutdown
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    log_info("Shutdown signal received")
    shutdown_event.set()

def start_web_server():
    """Start the Flask web server in a separate thread"""
    try:
        host = config.get("web_server", "host")
        port = config.get("web_server", "port")
        debug = config.get("web_server", "debug")
        
        # Start in a separate thread
        from threading import Thread
        web_thread = Thread(target=lambda: flask_app.run(
            host=host, 
            port=port, 
            debug=debug, 
            use_reloader=False
        ))
        web_thread.daemon = True
        web_thread.start()
        
        log_info(f"Web server started on {host}:{port}")
        return web_thread
    except Exception as e:
        log_error(f"Failed to start web server: {e}")
        return None

def main():
    """Main function - initialize and run the application"""
    try:
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        log_info("Starting Trilobot application")
        
        # Start control manager (logs internally)
        control_manager.start()
        
        # Start camera processor (logs internally if successful)
        log_info("Starting camera processor...")
        
        # Report Python and system information
        log_info(f"Python version: {sys.version}")
        log_info(f"System platform: {sys.platform}")
        
        # Check for picamera2 module
        picamera2_found = False
        try:
            from picamera2 import Picamera2
            picamera2_found = True
            log_info("PiCamera2 module is available")
        except ImportError as e:
            log_warning(f"PiCamera2 module not found: {e}")
            log_warning("Camera functionality may be limited")
        
        # Check camera status before starting
        camera_status = camera_processor.get_camera_status()
        log_info(f"Camera hardware available: {camera_status['available']}")
        if not camera_status['available']:
            log_warning(f"Camera hardware issue: {camera_status['error']}")
        
        # Try to start the camera
        if camera_processor.start():
            # Update camera mode in state tracker
            state_tracker.update_state('camera_mode', 'basic')
        else:
            log_warning(f"Failed to start camera processor: {camera_status['error']}")
        
        # Check for PS4 controller
        print("\n====== PS4 CONTROLLER SETUP ======")
        print("Checking for PS4 controller...")
        
        # First check if controller is already connected
        if ps4_controller.find_controller():
            print("✓ PS4 controller already connected!")
            if ps4_controller.start():
                log_info("PS4 controller started")
            else:
                log_warning("Failed to start PS4 controller - continuing with web controls only")
        else:
            # Not found, attempt to connect
            print("No controller found. Starting connection process...")
            # start() will handle the interactive connection process
            if ps4_controller.start():
                if ps4_controller.web_only_mode:
                    log_info("Running in web-only mode (no PS4 controller)")
                else:
                    log_info("PS4 controller connected and started")
            else:
                # User chose to exit the application
                log_error("User chose to exit without PS4 controller")
                sys.exit(0)
        
        # Start voice controller if enabled
        if config.get("voice", "enabled"):
            if voice_controller.start():
                log_info("Voice controller started")
            else:
                log_warning("Failed to start voice controller")
        
        # Start web server
        web_thread = start_web_server()
        if not web_thread:
            log_warning("Web server failed to start")
        
        # Announce successful startup if voice is enabled
        log_info("Attempting startup announcement...")
        if config.get("voice", "enabled"):
            try:
                # Use a short delay to ensure audio system is ready
                time.sleep(1.0)
                voice_controller.speak("Trilobot systems online. Camera activated.")
                log_info("Startup announcement sent to voice controller.")
            except Exception as e:
                log_error(f"Error during startup announcement: {e}")
        else:
            log_info("Voice control disabled, skipping announcement.")
        
        # Main loop - keep running until shutdown
        log_info("Trilobot application running. Press Ctrl+C to stop.")
        while not shutdown_event.is_set():
            time.sleep(0.1)
        
    except Exception as e:
        log_error(f"Error in main: {e}")
    finally:
        cleanup()

def cleanup():
    """Clean up and shut down all services"""
    log_info("Performing cleanup...")
    
    # Stop voice controller
    try:
        voice_controller.stop()
    except:
        pass
    
    # Stop PS4 controller
    try:
        ps4_controller.stop()
    except:
        pass
    
    # Stop camera processor
    try:
        camera_processor.stop()
    except:
        pass
    
    # Stop control manager
    try:
        control_manager.stop()
    except:
        pass
    
    log_info("Cleanup complete")

if __name__ == "__main__":
    main() 