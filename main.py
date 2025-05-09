#!/usr/bin/env python3
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
import socket
import platform
from pathlib import Path

# Only keep minimal message suppression that won't break functionality
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'  # Hide pygame welcome message

# Create global file for error redirection - will be accessible for cleanup
_devnull_file = open(os.devnull, 'w')
_old_stderr = sys.stderr

# Redirect stderr globally - we'll restore it after all potentially noisy imports
try:
    sys.stderr = _devnull_file
    
    # Import potentially noisy modules here to suppress their startup messages
    import pygame.mixer  # Suppress pygame audio initialization messages
except Exception as e:
    # If this fails, continue without redirection
    # But print a note about it for debugging
    print(f"Warning: Failed to redirect stderr to suppress audio messages: {e}")
    
    # Ensure we don't leave stderr in a bad state
    sys.stderr = _old_stderr

# Now restore stderr for normal operation
sys.stderr = _old_stderr
# Using print since logging isn't imported yet
print("Stderr restored after audio module imports")

# Import local modules
from debugging import log_info, log_error, log_warning, log_debug, state_tracker
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
        if camera_processor.start(): # UNCOMMENTED
            # Update camera mode in state tracker
            state_tracker.update_state('camera_mode', 'basic')
        else:
            log_warning(f"Failed to start camera processor: {camera_status['error']}")
        # log_warning("Camera processor start skipped for testing.") # REMOVED
        
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
        voice_available = True
        if config.get("voice", "enabled"):
            try:
                log_info("Attempting to start voice controller...")
                voice_start_success = False
                try:
                    voice_start_success = voice_controller.start()
                    if voice_start_success:
                        log_info("Voice controller started successfully")
                    else:
                        log_warning("Voice controller failed to start - continuing without voice control")
                        voice_available = False
                except Exception as vc_e:
                    log_error(f"Exception during voice controller startup: {vc_e}")
                    log_warning("Continuing without voice control due to error")
                    voice_available = False
            except Exception as e:
                log_error(f"Unhandled error starting voice controller: {e}")
                log_warning("Voice control disabled due to errors")
                voice_available = False
        else:
            log_info("Voice control disabled in config")
            voice_available = False
        
        # Start web server
        web_thread = start_web_server() # UNCOMMENTED
        if not web_thread:
            log_warning("Web server failed to start")
        #log_warning("Web server start skipped for testing.") # REMOVED
        
        # Announce successful startup if voice is enabled and available
        log_info("Attempting startup announcement...")
        if config.get("voice", "enabled") and voice_available and voice_start_success:
            try:
                # Use a short delay to ensure audio system is ready
                time.sleep(5.0)
                voice_controller.speak("Trilobot systems online. Camera activated.")
                log_info("Startup announcement sent to voice controller.")
            except Exception as e:
                log_error(f"Error during startup announcement: {e}")
                # Don't disable voice on announcement error - the core functionality might still work
        else:
            log_info("Voice control disabled or unavailable, skipping announcement.")
        
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
    
    # Restore stderr if it was redirected
    global _old_stderr, _devnull_file
    if '_old_stderr' in globals() and _old_stderr is not None:
        sys.stderr = _old_stderr
        log_debug("stderr restored")
    
    if '_devnull_file' in globals() and _devnull_file is not None:
        try:
            _devnull_file.close()
            log_debug("devnull file closed")
        except:
            pass
    
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