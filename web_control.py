"""
Web Control for Trilobot

This module provides a Flask web server for controlling the Trilobot via a browser.
It includes movement controls, LED controls, and camera streaming.
"""

from flask import Flask, render_template, jsonify, Response
import threading
import time
import io
import os
import logging
from threading import Condition

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker
from config import config
from control_manager import control_manager, ControlMode, ControlAction

logger = logging.getLogger('trilobot.web')

# Try to import hardware-specific modules
try:
    from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    hardware_available = True
except ImportError:
    # Mock for development without hardware
    hardware_available = False
    logger.warning("Hardware-specific modules not available. Using mock objects.")
    
    # Define constants that would normally be from trilobot
    NUM_BUTTONS = 6
    LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT = 0, 1
    LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT = 2, 3
    LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT = 4, 5
    
    # Mock Picamera2
    class MockPicamera2:
        def __init__(self):
            logger.warning("Using MockPicamera2 (no hardware)")
        
        def create_video_configuration(self, **kwargs):
            return {"mock": "config"}
        
        def configure(self, config):
            pass
        
        def start(self):
            logger.debug("Mock: Camera started")
        
        def start_recording(self, *args, **kwargs):
            logger.debug("Mock: Recording started")
        
        def stop(self):
            logger.debug("Mock: Camera stopped")
    
    Picamera2 = MockPicamera2
    MJPEGEncoder = type('MockMJPEGEncoder', (), {"__init__": lambda self, **kwargs: None})
    FileOutput = type('MockFileOutput', (), {"__init__": lambda self, *args: None})

# Initialize Flask
app = Flask(__name__)

# Global variables
camera = None
output = None
overlay_mode = 'normal'
button_states = {
    'triangle': False,
    'circle': False,
    'cross': False,
    'square': False
}

# Light show thread
light_show_thread = None
stop_light_shows = threading.Event()

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

def init_camera():
    """Initialize the Raspberry Pi camera"""
    global camera, output
    
    if not hardware_available:
        log_warning("Camera initialization skipped - hardware not available")
        return False
    
    try:
        resolution = config.get("camera", "resolution")
        framerate = config.get("camera", "framerate")
        
        camera = Picamera2()
        camera_config = camera.create_video_configuration(
            main={"size": (resolution[0], resolution[1])},
            encode="main",
            buffer_count=4
        )
        camera.configure(camera_config)
        output = StreamingOutput()
        encoder = MJPEGEncoder(bitrate=8000000)
        camera.start_recording(encoder, FileOutput(output))
        log_info("Camera initialized successfully")
        return True
    except Exception as e:
        log_error(f"Camera initialization error: {e}")
        return False

@app.route('/')
def index():
    """Serve the main page"""
    stream_port = config.get("camera", "stream_port")
    return render_template('index.html', stream_url=f'/stream.mjpg')

@app.route('/overlay/<mode>')
def set_overlay(mode):
    """Set the camera overlay mode"""
    global overlay_mode
    try:
        overlay_mode = mode
        log_info(f"Overlay mode set to: {mode}")
        return jsonify({'status': 'success', 'mode': mode})
    except Exception as e:
        log_error(f"Overlay error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

def knight_rider_effect():
    """Knight Rider light effect"""
    log_info("Starting Knight Rider effect")
    
    if not hardware_available:
        return
    
    try:
        from trilobot import Trilobot, LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_FRONT_RIGHT
        tbot = Trilobot()
        
        lights = [
            LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT,
            LIGHT_REAR_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_FRONT_RIGHT
        ]
        
        interval = config.get("leds", "knight_rider_interval")
        
        while not stop_light_shows.is_set() and control_manager.knight_rider_active:
            # Forward
            for i in range(len(lights)):
                if stop_light_shows.is_set() or not control_manager.knight_rider_active:
                    break
                tbot.clear_underlighting(show=False)
                tbot.set_underlight(lights[i], (255, 0, 0), show=True)
                time.sleep(interval)
            # Backward
            for i in range(len(lights)-2, 0, -1):
                if stop_light_shows.is_set() or not control_manager.knight_rider_active:
                    break
                tbot.clear_underlighting(show=False)
                tbot.set_underlight(lights[i], (255, 0, 0), show=True)
                time.sleep(interval)
    except Exception as e:
        log_error(f"Knight Rider effect error: {e}")

def party_mode_effect():
    """Party mode light effect"""
    log_info("Starting Party mode effect")
    
    if not hardware_available:
        return
    
    try:
        from trilobot import Trilobot
        tbot = Trilobot()
        
        colors = [
            (255, 0, 0),    # Red
            (0, 255, 0),    # Green
            (0, 0, 255),    # Blue
            (255, 255, 0),  # Yellow
            (255, 0, 255),  # Magenta
            (0, 255, 255),  # Cyan
        ]
        
        interval = config.get("leds", "party_mode_interval")
        
        while not stop_light_shows.is_set() and control_manager.party_mode_active:
            for color in colors:
                if stop_light_shows.is_set() or not control_manager.party_mode_active:
                    break
                tbot.fill_underlighting(color)
                time.sleep(interval)
    except Exception as e:
        log_error(f"Party mode effect error: {e}")

def start_light_show(effect_function):
    """Start a light show in a separate thread"""
    global light_show_thread
    stop_light_shows.clear()
    
    if light_show_thread and light_show_thread.is_alive():
        stop_light_shows.set()
        light_show_thread.join()
    
    light_show_thread = threading.Thread(target=effect_function)
    light_show_thread.daemon = True
    light_show_thread.start()

@app.route('/button/<button_name>/<action>')
def handle_button(button_name, action):
    """Handle button presses from web interface"""
    log_info(f"Button press received: {button_name} - {action}")
    
    try:
        is_active = (action == 'press')
        
        # Set web control mode
        control_manager.set_mode(ControlMode.WEB)
        
        if button_name == 'triangle':
            if is_active:
                # Toggle button LEDs
                control_manager.button_leds_active = not control_manager.button_leds_active
                if hardware_available:
                    from trilobot import Trilobot, NUM_BUTTONS
                    tbot = Trilobot()
                    for led in range(NUM_BUTTONS):
                        tbot.set_button_led(led, control_manager.button_leds_active)
                
        elif button_name == 'circle':
            if is_active:
                # Toggle Knight Rider effect
                control_manager.execute_action(ControlAction.TOGGLE_KNIGHT_RIDER)
                if control_manager.knight_rider_active:
                    start_light_show(knight_rider_effect)
                
        elif button_name == 'cross':
            if is_active:
                # Clear all effects
                control_manager.knight_rider_active = False
                control_manager.party_mode_active = False
                stop_light_shows.set()
                
                if hardware_available:
                    from trilobot import Trilobot, NUM_BUTTONS
                    tbot = Trilobot()
                    tbot.clear_underlighting()
                    for led in range(NUM_BUTTONS):
                        tbot.set_button_led(led, False)
                
                control_manager.button_leds_active = False
                
        elif button_name == 'square':
            if is_active:
                # Toggle party mode
                control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE)
                if control_manager.party_mode_active:
                    start_light_show(party_mode_effect)
        
        return jsonify({
            'status': 'success',
            'button': button_name,
            'action': action,
            'states': {
                'button_leds': control_manager.button_leds_active,
                'knight_rider': control_manager.knight_rider_active,
                'party_mode': control_manager.party_mode_active
            }
        })
        
    except Exception as e:
        log_error(f"Button error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands from web interface"""
    try:
        # Set web control mode
        control_manager.set_mode(ControlMode.WEB)
        
        if action == 'start':
            if direction == 'forward':
                control_manager.execute_action(ControlAction.MOVE_FORWARD)
            elif direction == 'backward':
                control_manager.execute_action(ControlAction.MOVE_BACKWARD)
            elif direction == 'left':
                control_manager.execute_action(ControlAction.TURN_LEFT)
            elif direction == 'right':
                control_manager.execute_action(ControlAction.TURN_RIGHT)
        elif action == 'stop':
            control_manager.execute_action(ControlAction.STOP)
            
        return jsonify({
            'status': 'success',
            'direction': direction,
            'action': action
        })
        
    except Exception as e:
        log_error(f"Movement error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop')
def stop():
    """Stop all motors"""
    try:
        control_manager.execute_action(ControlAction.EMERGENCY_STOP)
        return jsonify({'status': 'success', 'message': 'Motors stopped'})
    except Exception as e:
        log_error(f"Stop error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stream.mjpg')
def stream():
    """Video streaming route"""
    def generate():
        if not hardware_available or not output:
            # Return a dummy frame if hardware is not available
            dummy_frame = b''
            while True:
                yield (b'--FRAME\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + dummy_frame + b'\r\n')
                time.sleep(0.1)
        
        while True:
            with output.condition:
                output.condition.wait()
                frame = output.frame
            yield (b'--FRAME\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    
    return Response(generate(),
                   mimetype='multipart/x-mixed-replace; boundary=FRAME')

def cleanup():
    """Cleanup function to run when shutting down"""
    log_info("Cleaning up web control resources")
    
    # Stop light shows
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join(timeout=1.0)
    
    # Stop control manager
    control_manager.stop()
    
    # Clean up camera
    if camera:
        try:
            camera.stop_recording()
            camera.stop()
        except:
            pass

@app.route('/test')
def test():
    """Test if the web server is running"""
    return "Web control server is running!"

def main():
    """Main function to start the web control server"""
    try:
        log_info("Starting initialization...")
        
        # Start control manager
        control_manager.start()
        
        # Initialize camera
        init_camera()
            
        # Start Flask server
        web_port = config.get("web_server", "port")
        web_host = config.get("web_server", "host")
        debug_mode = config.get("web_server", "debug")
        
        log_info(f"Starting web interface on {web_host}:{web_port}")
        app.run(host=web_host, port=web_port, threaded=True, debug=debug_mode)
        
    except Exception as e:
        log_error(f"Web control startup error: {e}")
        raise
    finally:
        cleanup()

if __name__ == '__main__':
    main()