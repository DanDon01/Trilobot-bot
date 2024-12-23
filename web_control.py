from flask import Flask, render_template, jsonify, Response
from trilobot import Trilobot, NUM_BUTTONS
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

app = Flask(__name__)
tbot = Trilobot()

# Global variables
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
        self.rec_dot_visible = True  # For blinking REC dot
        self.last_blink = time.time()
        self.blink_interval = 1.0  # Blink every second
        
    def write(self, buf):
        try:
            # Convert buffer to numpy array
            nparr = np.frombuffer(buf, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return
                
            # Get frame dimensions
            h, w = frame.shape[:2]
            
            # Create semi-transparent overlay for text background
            overlay = frame.copy()
            
            # Add digital clock (top right)
            current_time = datetime.now().strftime('%H:%M:%S')
            clock_text_size = cv2.getTextSize(current_time, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)[0]
            clock_x = w - clock_text_size[0] - 20
            # Draw semi-transparent background for clock
            cv2.rectangle(overlay, 
                        (clock_x - 10, 10), 
                        (w - 10, 50), 
                        (0, 0, 0), 
                        -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            # Draw clock text
            cv2.putText(frame, current_time, 
                       (clock_x, 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
            
            # Add REC indicator with blinking dot (top left)
            current_time = time.time()
            if current_time - self.last_blink >= self.blink_interval:
                self.rec_dot_visible = not self.rec_dot_visible
                self.last_blink = current_time
            
            if self.rec_dot_visible:
                # Draw semi-transparent background for REC
                cv2.rectangle(overlay, 
                            (10, 10), 
                            (120, 50), 
                            (0, 0, 0), 
                            -1)
                cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
                # Draw REC text and dot
                cv2.circle(frame, (30, 30), 8, (0, 0, 255), -1)  # Red dot
                cv2.putText(frame, "REC", 
                           (50, 40),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            # Add date (bottom left)
            current_date = datetime.now().strftime('%Y-%m-%d')
            # Draw semi-transparent background for date
            cv2.rectangle(overlay, 
                        (10, h - 50), 
                        (200, h - 10), 
                        (0, 0, 0), 
                        -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            # Draw date text
            cv2.putText(frame, current_date, 
                       (20, h - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            
            # Apply mode-specific overlays
            if overlay_mode == 'night_vision':
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = cv2.applyColorMap(frame, cv2.COLORMAP_BONE)
                
            elif overlay_mode == 'targeting':
                # Add targeting overlay
                center_x, center_y = w//2, h//2
                cv2.line(frame, (center_x - 20, center_y), 
                        (center_x + 20, center_y), (0, 0, 255), 2)
                cv2.line(frame, (center_x, center_y - 20), 
                        (center_x, center_y + 20), (0, 0, 255), 2)
                cv2.circle(frame, (center_x, center_y), 50, (0, 0, 255), 1)
            
            # Encode frame
            _, encoded_frame = cv2.imencode('.jpg', frame)
            
            with self.condition:
                self.frame = encoded_frame.tobytes()
                self.condition.notify_all()
                
        except Exception as e:
            print(f"Frame processing error: {e}")

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
                print(f"Streaming error: {e}")
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def init_camera():
    global camera, output
    try:
        # Kill any existing camera processes
        os.system('sudo fuser -k /dev/video0 2>/dev/null')
        time.sleep(1)
        
        camera = Picamera2()
        # Improved camera configuration
        camera_config = camera.create_video_configuration(
            main={"size": (1280, 720)},  # Higher resolution
            encode="main",
            buffer_count=4
        )
        camera.configure(camera_config)
        output = StreamingOutput()
        # Increased bitrate for better quality
        encoder = MJPEGEncoder(bitrate=8000000)  # 8Mbps
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
    """Run the Knight Rider light effect"""
    lights = [
        LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT,
        LIGHT_REAR_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_FRONT_RIGHT
    ]
    current_led = 0
    direction = 1
    
    while not stop_light_shows.is_set() and knight_rider_active:
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(lights[current_led], (255, 0, 0), show=True)
        
        current_led += direction
        if current_led >= len(lights) - 1:
            current_led = len(lights) - 2
            direction = -1
        elif current_led <= 0:
            current_led = 1
            direction = 1
            
        time.sleep(0.1)

def party_mode_effect():
    """Run the party mode light effect"""
    colors = [
        (255, 0, 0),    # Red
        (0, 255, 0),    # Green
        (0, 0, 255),    # Blue
        (255, 255, 0),  # Yellow
        (255, 0, 255),  # Magenta
        (0, 255, 255),  # Cyan
    ]
    current_color = 0
    
    while not stop_light_shows.is_set() and party_mode_active:
        tbot.fill_underlighting(colors[current_color])
        current_color = (current_color + 1) % len(colors)
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
    """Handle PS4-style button presses"""
    global button_leds_active, knight_rider_active, party_mode_active
    
    try:
        is_active = (action == 'press')
        
        if button_name == 'triangle':
            # Triangle - Toggle button LEDs
            if is_active:
                button_leds_active = not button_leds_active
                for led in range(NUM_BUTTONS):
                    tbot.set_button_led(led, button_leds_active)
                
        elif button_name == 'circle':
            # Circle - Knight Rider effect
            if is_active:
                knight_rider_active = not knight_rider_active
                party_mode_active = False
                if knight_rider_active:
                    start_light_show(knight_rider_effect)
                else:
                    stop_light_shows.set()
                    tbot.clear_underlighting()
                
        elif button_name == 'cross':
            # Cross - Clear all effects
            if is_active:
                knight_rider_active = False
                party_mode_active = False
                stop_light_shows.set()
                tbot.clear_underlighting()
                for led in range(NUM_BUTTONS):
                    tbot.set_button_led(led, False)
                button_leds_active = False
                
        elif button_name == 'square':
            # Square - Party mode
            if is_active:
                party_mode_active = not party_mode_active
                knight_rider_active = False
                if party_mode_active:
                    start_light_show(party_mode_effect)
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
        print(f"Button error: {e}")
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
            try:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                    
                if frame is not None:
                    yield (b'--FRAME\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            except Exception as e:
                print(f"Streaming error: {e}")
                break
    
    return Response(generate(),
                   mimetype='multipart/x-mixed-replace; boundary=FRAME')

def cleanup():
    """Cleanup function to run when shutting down"""
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join()
    tbot.disable_motors()
    tbot.clear_underlighting()
    for led in range(NUM_BUTTONS):
        tbot.set_button_led(led, False)

if __name__ == '__main__':
    try:
        # Initialize camera
        if init_camera():
            # Start camera server
            camera_server = StreamingServer(('', 8000), StreamingHandler)
            server_thread = threading.Thread(target=camera_server.serve_forever)
            server_thread.daemon = True
            server_thread.start()
        
        # Start Flask app
        app.run(host='0.0.0.0', port=5000, debug=False)  # Set debug to False
    except Exception as e:
        print(f"Startup error: {e}")
    finally:
        cleanup()