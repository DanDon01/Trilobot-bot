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
from camera_processor import camera_processor

logger = logging.getLogger('trilobot.web')

# Try to import hardware-specific modules
try:
    from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
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

# Initialize Flask
app = Flask(__name__)

# Global variables
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

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html', stream_url=f'/stream.mjpg')

@app.route('/overlay/<mode>')
def set_overlay(mode):
    """Set the camera overlay mode"""
    try:
        camera_processor.set_overlay_mode(mode)
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
        output = camera_processor.get_stream()
        
        if not camera_processor.running:
            # Generate a basic placeholder image for the stream when camera is not available
            import io
            try:
                # Try to use PIL to generate a simple image
                from PIL import Image, ImageDraw, ImageFont
                
                # Create a mock frame with "Camera Unavailable" text
                def create_mock_frame():
                    width, height = 640, 480
                    img = Image.new('RGB', (width, height), color=(70, 70, 70))
                    draw = ImageDraw.Draw(img)
                    
                    # Draw text
                    text = "Camera Unavailable"
                    text_width = draw.textlength(text, font=None)
                    draw.text(
                        ((width - text_width) / 2, height // 2 - 10),
                        text,
                        fill=(255, 255, 255)
                    )
                    
                    # Add timestamp for changing image
                    timestamp = time.strftime("%H:%M:%S")
                    draw.text(
                        (10, height - 30),
                        f"Time: {timestamp}",
                        fill=(200, 200, 200)
                    )
                    
                    # Convert to JPEG bytes
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    return img_byte_arr.getvalue()
                
                # Return mock frames
                while True:
                    mock_frame = create_mock_frame()
                    yield (b'--FRAME\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + mock_frame + b'\r\n')
                    time.sleep(1)  # Update once per second
                    
            except ImportError:
                # If PIL is not available, use an even simpler approach
                log_warning("PIL not available for mock video. Using minimal fallback.")
                empty_frame = b''
                while True:
                    yield (b'--FRAME\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + empty_frame + b'\r\n')
                    time.sleep(0.5)
        
        # Normal camera streaming when available
        while True:
            try:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                
                # Apply any overlay if needed
                processed_frame = camera_processor.apply_overlay(frame)
                
                yield (b'--FRAME\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + processed_frame + b'\r\n')
            except Exception as e:
                log_error(f"Stream error: {e}")
                time.sleep(0.5)
    
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

@app.route('/test')
def test():
    """Test if the web server is running"""
    return "Web control server is running!"

@app.route('/camera_status')
def camera_status():
    """Get the status of the camera"""
    try:
        status = camera_processor.get_camera_status()
        return jsonify(status)
    except Exception as e:
        log_error(f"Error getting camera status: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

def main():
    """Main function to start the web control server"""
    try:
        log_info("Starting initialization...")
        
        # Start control manager
        control_manager.start()
        
        # Initialize and start camera processor
        camera_processor.start()
            
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