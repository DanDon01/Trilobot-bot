from flask import Flask, render_template, jsonify, Response
from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import cv2
import numpy as np
from datetime import datetime
import io
import time
import threading
import os
from threading import Condition
import socketserver
from http import server
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__)

# Initialize Trilobot ONCE
tbot = None

def get_trilobot():
    global tbot
    if tbot is None:
        tbot = Trilobot()
    return tbot

# Use get_trilobot() wherever you need the Trilobot instance
tbot = get_trilobot()

# Global variables for movement
SPEED = 1.0
ACCELERATION = 0.5
current_speeds = {'left': 0, 'right': 0}
camera = None
output = None
overlay_mode = 'normal'
button_states = {
    'triangle': False,
    'circle': False,
    'cross': False,
    'square': False
}

# Add these global variables for tracking states
button_leds_active = False
knight_rider_active = False
party_mode_active = False
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
    global camera, output
    try:
        camera = Picamera2()
        camera_config = camera.create_video_configuration(
            main={"size": (1280, 720)},
            encode="main",
            buffer_count=4
        )
        camera.configure(camera_config)
        output = StreamingOutput()
        encoder = MJPEGEncoder(bitrate=8000000)
        camera.start_recording(encoder, FileOutput(output))
        print("Camera initialized successfully")
        return True
    except Exception as e:
        print(f"Camera initialization error: {e}")
        return False

@app.route('/')
def index():
    """Serve the main page"""
    # Pass the stream URL to the template
    return render_template('index.html', stream_url='/stream.mjpg')

@app.route('/overlay/<mode>')
def set_overlay(mode):
    global overlay_mode
    try:
        overlay_mode = mode
        print(f"Overlay mode set to: {mode}")
        return jsonify({'status': 'success', 'mode': mode})
    except Exception as e:
        print(f"Overlay error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

def knight_rider_effect():
    """Knight Rider light effect"""
    print("Starting Knight Rider effect")  # Debug print
    lights = [
        LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT,
        LIGHT_REAR_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_FRONT_RIGHT
    ]
    while not stop_light_shows.is_set() and knight_rider_active:
        # Forward
        for i in range(len(lights)):
            if stop_light_shows.is_set() or not knight_rider_active:
                break
            tbot.clear_underlighting(show=False)
            tbot.set_underlight(lights[i], (255, 0, 0), show=True)
            time.sleep(0.1)
        # Backward
        for i in range(len(lights)-2, 0, -1):
            if stop_light_shows.is_set() or not knight_rider_active:
                break
            tbot.clear_underlighting(show=False)
            tbot.set_underlight(lights[i], (255, 0, 0), show=True)
            time.sleep(0.1)

def party_mode_effect():
    """Party mode light effect"""
    print("Starting Party mode effect")  # Debug print
    colors = [
        (255, 0, 0),    # Red
        (0, 255, 0),    # Green
        (0, 0, 255),    # Blue
        (255, 255, 0),  # Yellow
        (255, 0, 255),  # Magenta
        (0, 255, 255),  # Cyan
    ]
    while not stop_light_shows.is_set() and party_mode_active:
        for color in colors:
            if stop_light_shows.is_set() or not party_mode_active:
                break
            tbot.fill_underlighting(color)
            time.sleep(0.2)

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
    """Handle button presses"""
    global button_leds_active, knight_rider_active, party_mode_active
    
    print(f"Button press received: {button_name} - {action}")  # Debug print
    
    try:
        is_active = (action == 'press')
        
        if button_name == 'triangle':
            if is_active:
                print("Triangle pressed - toggling button LEDs")  # Debug print
                button_leds_active = not button_leds_active
                for led in range(NUM_BUTTONS):
                    tbot.set_button_led(led, button_leds_active)
                
        elif button_name == 'circle':
            if is_active:
                print("Circle pressed - toggling Knight Rider effect")  # Debug print
                knight_rider_active = not knight_rider_active
                party_mode_active = False  # Stop party mode if running
                if knight_rider_active:
                    stop_light_shows.clear()
                    threading.Thread(target=knight_rider_effect, daemon=True).start()
                else:
                    stop_light_shows.set()
                    tbot.clear_underlighting()
                
        elif button_name == 'cross':
            if is_active:
                print("Cross pressed - clearing all effects")  # Debug print
                # Clear all effects
                knight_rider_active = False
                party_mode_active = False
                stop_light_shows.set()
                tbot.clear_underlighting()
                for led in range(NUM_BUTTONS):
                    tbot.set_button_led(led, False)
                button_leds_active = False
                
        elif button_name == 'square':
            if is_active:
                print("Square pressed - toggling party mode")  # Debug print
                party_mode_active = not party_mode_active
                knight_rider_active = False  # Stop knight rider if running
                if party_mode_active:
                    stop_light_shows.clear()
                    threading.Thread(target=party_mode_effect, daemon=True).start()
                else:
                    stop_light_shows.set()
                    tbot.clear_underlighting()
        
        return jsonify({
            'status': 'success',
            'button': button_name,
            'action': action,
            'states': {
                'button_leds': button_leds_active,
                'knight_rider': knight_rider_active,
                'party_mode': party_mode_active
            }
        })
        
    except Exception as e:
        print(f"Button error: {e}")  # Debug print
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands"""
    try:
        speed = SPEED  # Using the global SPEED value
        
        if action == 'start':
            if direction == 'forward':
                tbot.set_left_speed(speed)
                tbot.set_right_speed(speed)
            elif direction == 'backward':
                tbot.set_left_speed(-speed)
                tbot.set_right_speed(-speed)
            elif direction == 'left':
                tbot.set_left_speed(-speed)
                tbot.set_right_speed(speed)
            elif direction == 'right':
                tbot.set_left_speed(speed)
                tbot.set_right_speed(-speed)
        elif action == 'stop':
            tbot.disable_motors()
            
        return jsonify({
            'status': 'success',
            'direction': direction,
            'action': action
        })
        
    except Exception as e:
        print(f"Movement error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop')
def stop():
    """Stop all motors"""
    try:
        tbot.disable_motors()
        return jsonify({'status': 'success', 'message': 'Motors stopped'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# Add this route for the camera stream
@app.route('/stream.mjpg')
def stream():
    """Video streaming route"""
    def generate():
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
    print("Cleaning up...")  # Debug print
    stop_light_shows.set()
    tbot.disable_motors()
    tbot.clear_underlighting()
    for led in range(NUM_BUTTONS):
        tbot.set_button_led(led, False)

# Add a basic test route
@app.route('/test')
def test():
    return "Web control server is running!"

def main():
    """Main function to start Flask server"""
    try:
        logger.info("Starting initialization...")
        
        # Initialize camera
        if not init_camera():
            logger.error("Failed to initialize camera")
            return
            
        # Start Flask server
        logger.info("Starting web interface on port 5000...")
        app.run(host='0.0.0.0', port=5000, threaded=True)
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    finally:
        cleanup()

if __name__ == '__main__':
    main()