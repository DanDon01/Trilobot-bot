from flask import Flask, render_template, jsonify
from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT
from trilobot import LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
import threading
import time
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import io
import logging
import socketserver
from http import server
from threading import Condition
import cv2
import numpy as np
from datetime import datetime

app = Flask(__name__)
tbot = Trilobot()

# Configuration
SPEED = 1.0        # Maximum speed
control_lock = threading.Lock()

# Light show constants
KNIGHT_RIDER_INTERVAL = 0.1
PARTY_MODE_INTERVAL = 0.2

# Colors
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
MAGENTA = (255, 0, 255)
CYAN = (0, 255, 255)

# Light mapping for effects
KNIGHT_RIDER_MAPPING = [
    LIGHT_REAR_LEFT,
    LIGHT_MIDDLE_LEFT,
    LIGHT_FRONT_LEFT,
    LIGHT_FRONT_RIGHT,
    LIGHT_MIDDLE_RIGHT,
    LIGHT_REAR_RIGHT
]

PARTY_COLORS = [
    RED,        # Red
    GREEN,      # Green
    BLUE,       # Blue
    YELLOW,     # Yellow
    MAGENTA,    # Magenta
    CYAN,       # Cyan
    (255, 128, 0),  # Orange
    (128, 0, 255),  # Purple
]

# Global state
button_leds_active = False
knight_rider_active = False
party_mode_active = False
tank_mode_active = False
light_show_thread = None
stop_light_shows = threading.Event()

# Add these global variables at the top
current_speeds = {'left': 0, 'right': 0}
is_moving = False
ACCELERATION = 0.5  # Faster acceleration response

# Add these constants for overlay settings
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.7
THICKNESS = 2
WHITE = (255, 255, 255)
RED = (0, 0, 255)  # BGR format
GREEN = (0, 255, 0)

# Add these classes for camera streaming
class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()
        self.overlay = CameraOverlay()

    def write(self, buf):
        nparr = np.frombuffer(buf, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Apply selected overlay
        frame = self.overlay.apply_overlay(frame)
        
        # Encode and store the frame
        _, encoded_frame = cv2.imencode('.jpg', frame)
        with self.condition:
            self.frame = encoded_frame.tobytes()
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

# Initialize camera
def init_camera():
    global picam2, output, encoder
    try:
        # Try to clean up any existing camera instances
        if 'picam2' in globals() and picam2:
            try:
                picam2.stop_recording()
                picam2.close()
            except:
                pass

        # Small delay to ensure camera is released
        time.sleep(1)
        
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
        output = StreamingOutput()
        encoder = MJPEGEncoder(bitrate=1000000)
        picam2.start_recording(encoder, FileOutput(output))
        return output
    except Exception as e:
        print(f"Camera initialization error: {e}")
        return None

# Start camera server
def start_camera_server():
    address = ('', 8000)  # Port 8000
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()

def knight_rider_effect():
    """Run the Knight Rider light effect"""
    current_led = 0
    direction = 1
    
    while not stop_light_shows.is_set() and knight_rider_active:
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(KNIGHT_RIDER_MAPPING[current_led], RED, show=True)
        
        # Update LED position
        current_led += direction
        
        # Change direction at ends
        if current_led >= len(KNIGHT_RIDER_MAPPING) - 1:
            current_led = len(KNIGHT_RIDER_MAPPING) - 2
            direction = -1
        elif current_led <= 0:
            current_led = 1
            direction = 1
            
        time.sleep(KNIGHT_RIDER_INTERVAL)

def party_mode_effect():
    """Run the party mode light effect"""
    color_index = 0
    
    while not stop_light_shows.is_set() and party_mode_active:
        tbot.fill_underlighting(PARTY_COLORS[color_index])
        color_index = (color_index + 1) % len(PARTY_COLORS)
        time.sleep(PARTY_MODE_INTERVAL)

def start_light_show(effect_function):
    """Start a light show in a separate thread"""
    global light_show_thread
    
    # Stop any running light shows
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join()
    
    # Reset the stop event and start new light show
    stop_light_shows.clear()
    light_show_thread = threading.Thread(target=effect_function)
    light_show_thread.start()

@app.route('/')
def index():
    """Serve the main control page"""
    return render_template('index.html')

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands with smooth acceleration"""
    global current_speeds, is_moving
    
    try:
        if action == 'start':
            is_moving = True
            speed = SPEED if not tank_mode_active else SPEED * 0.7
            
            if direction == 'forward':
                target_speeds = {'left': speed, 'right': speed}
            elif direction == 'backward':
                target_speeds = {'left': -speed, 'right': -speed}
            elif direction == 'left':
                if tank_mode_active:
                    target_speeds = {'left': -speed, 'right': speed}
                else:
                    target_speeds = {'left': -speed/2, 'right': speed/2}
            elif direction == 'right':
                if tank_mode_active:
                    target_speeds = {'left': speed, 'right': -speed}
                else:
                    target_speeds = {'left': speed/2, 'right': -speed/2}
                    
            # Smoothly adjust speeds
            while is_moving and any(abs(current_speeds[motor] - target_speeds[motor]) > 0.01 for motor in ['left', 'right']):
                for motor in ['left', 'right']:
                    diff = target_speeds[motor] - current_speeds[motor]
                    if abs(diff) > ACCELERATION:
                        current_speeds[motor] += ACCELERATION if diff > 0 else -ACCELERATION
                    else:
                        current_speeds[motor] = target_speeds[motor]
                
                # Apply the new speeds
                tbot.set_left_speed(current_speeds['left'])
                tbot.set_right_speed(current_speeds['right'])
                time.sleep(0.02)  # Small delay for smooth acceleration
                
        elif action == 'stop':
            is_moving = False
            # Smoothly stop
            while any(abs(current_speeds[motor]) > 0.01 for motor in ['left', 'right']):
                for motor in ['left', 'right']:
                    if abs(current_speeds[motor]) > ACCELERATION:
                        current_speeds[motor] -= ACCELERATION if current_speeds[motor] > 0 else -ACCELERATION
                    else:
                        current_speeds[motor] = 0
                
                tbot.set_left_speed(current_speeds['left'])
                tbot.set_right_speed(current_speeds['right'])
                time.sleep(0.02)
            
            tbot.disable_motors()
            current_speeds = {'left': 0, 'right': 0}
            
        return jsonify({
            'status': 'success',
            'direction': direction,
            'action': action,
            'speeds': current_speeds
        })
        
    except Exception as e:
        is_moving = False
        tbot.disable_motors()
        current_speeds = {'left': 0, 'right': 0}
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/toggle/<mode>')
def toggle_mode(mode):
    """Toggle various modes and features"""
    global button_leds_active, knight_rider_active, party_mode_active, tank_mode_active
    
    try:
        if mode == 'knight':
            knight_rider_active = not knight_rider_active
            party_mode_active = False
            
            if knight_rider_active:
                start_light_show(knight_rider_effect)
            else:
                stop_light_shows.set()
                tbot.clear_underlighting()
                
            return jsonify({'status': 'success', 'active': knight_rider_active})
            
        elif mode == 'party':
            party_mode_active = not party_mode_active
            knight_rider_active = False
            
            if party_mode_active:
                start_light_show(party_mode_effect)
            else:
                stop_light_shows.set()
                tbot.clear_underlighting()
                
            return jsonify({'status': 'success', 'active': party_mode_active})
            
        elif mode == 'tank':
            tank_mode_active = not tank_mode_active
            return jsonify({'status': 'success', 'active': tank_mode_active})
            
        elif mode == 'leds':
            button_leds_active = not button_leds_active
            for led in range(NUM_BUTTONS):
                tbot.set_button_led(led, button_leds_active)
            return jsonify({'status': 'success', 'active': button_leds_active})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/status')
def get_status():
    """Get current status of all modes"""
    return jsonify({
        'knight_rider': knight_rider_active,
        'party_mode': party_mode_active,
        'tank_mode': tank_mode_active,
        'button_leds': button_leds_active
    })

def cleanup():
    """Cleanup function to run when shutting down"""
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join()
    tbot.disable_motors()
    tbot.clear_underlighting()
    for led in range(NUM_BUTTONS):
        tbot.set_button_led(led, False)

class CameraOverlay:
    def __init__(self):
        self.overlay_mode = 'normal'  # normal, night_vision, targeting
        
    def apply_overlay(self, frame):
        if self.overlay_mode == 'normal':
            return self._normal_overlay(frame)
        elif self.overlay_mode == 'night_vision':
            return self._night_vision_overlay(frame)
        elif self.overlay_mode == 'targeting':
            return self._targeting_overlay(frame)
        return frame
    
    def _normal_overlay(self, frame):
        # Basic overlay (timestamp, battery, etc.)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cv2.putText(frame, timestamp, (10, 30), FONT, FONT_SCALE, WHITE, THICKNESS)
        return frame
    
    def _night_vision_overlay(self, frame):
        # Add night vision effect
        frame = cv2.applyColorMap(frame, cv2.COLORMAP_BONE)
        cv2.putText(frame, "NIGHT VISION", (frame.shape[1]//2 - 100, 30), 
                   FONT, FONT_SCALE, GREEN, THICKNESS)
        return frame
    
    def _targeting_overlay(self, frame):
        # Add targeting overlay
        h, w = frame.shape[:2]
        center = (w//2, h//2)
        
        # Draw targeting circles
        cv2.circle(frame, center, 50, RED, 2)
        cv2.circle(frame, center, 75, RED, 1)
        cv2.circle(frame, center, 100, RED, 1)
        
        # Draw crosshairs
        cv2.line(frame, (center[0], 0), (center[0], h), RED, 1)
        cv2.line(frame, (0, center[1]), (w, center[1]), RED, 1)
        
        return frame

@app.route('/overlay/<mode>')
def set_overlay(mode):
    if hasattr(output, 'overlay'):
        output.overlay.overlay_mode = mode
        return jsonify({'status': 'success', 'mode': mode})
    return jsonify({'status': 'error', 'message': 'Overlay not available'})

if __name__ == '__main__':
    try:
        # Try to initialize camera
        camera_active = False
        try:
            output = init_camera()
            if output:
                camera_thread = threading.Thread(target=start_camera_server)
                camera_thread.daemon = True
                camera_thread.start()
                camera_active = True
                print("Camera initialized successfully")
            else:
                print("Camera initialization failed - web control will run without camera")
        except Exception as e:
            print(f"Camera error: {e}")
            print("Web control will run without camera")

        # Start Flask app
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        cleanup()
        if camera_active and 'picam2' in globals():
            try:
                picam2.stop_recording()
                picam2.close()
            except:
                pass