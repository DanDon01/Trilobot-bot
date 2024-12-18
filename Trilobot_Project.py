from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
from trilobot.simple_controller import SimpleController
import picamera2
import subprocess
import time
import math
import io
import logging
import socketserver
import datetime
from multiprocessing import Process
from threading import Condition
from http import server
from time import sleep

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

from evdev import InputDevice, ecodes, list_devices

# Initialize the Trilobot
tbot = Trilobot()

# Define some common colours to use later
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
GREEN = (0, 255, 0)
CYAN = (0, 255, 255)
BLUE = (0, 0, 255)
MAGENTA = (255, 0, 255)
BLACK = (0, 0, 0)

# Default values for the distance_reading() function
COLLISION_THRESHOLD_CM  = 22
MAX_NUM_READINGS        = 10
MAX_TIMEOUT_SEC         = 25
MAX_NUM_SAMPLES         = 3

# Speed parametners
NORMAL_LEFT_SPEED       = 0.65
NORMAL_RIGHT_SPEED      = 0.65

# Turning parameters
TURN_SPEED              = 0.65
TURN_TIME_SEC           = 0.55
TURN_RIGHT_PERCENT      = 65

# Backup parameters
BACKUP_LOOPS            = 5
BACKUP_TIME_SEC         = 0.15

'''
  Setup the underlighting
'''
DEFAULT_BLINK_COLOR     = BLUE
DEFAULT_BLINK_RATE_SEC  = 0.25
DEFAULT_NUM_CYCLES      = 1

# Light groups
LEFT_LIGHTS             = [ LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT ]
RIGHT_LIGHTS            = [ LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_RIGHT ]
REAR_LIGHTS             = [ LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT ]
FRONT_LIGHTS            = [ LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT ]

""" Set underlighting using separate red, green, and blue values
tbot.set_underlight(LIGHT_FRONT_LEFT, 255, 0, 0, show=False)      # Red
tbot.set_underlight(LIGHT_MIDDLE_LEFT, 255, 255, 0, show=False)   # Yellow
tbot.set_underlight(LIGHT_REAR_LEFT, 0, 255, 0, show=False)       # Green
tbot.set_underlight(LIGHT_REAR_RIGHT, 0, 255, 255, show=False)    # Cyan
tbot.set_underlight(LIGHT_MIDDLE_RIGHT, 0, 0, 255, show=False)    # Blue
tbot.set_underlight(LIGHT_FRONT_RIGHT, 255, 0, 255, show=False)   # Magenta """

TURN_DISTANCE = 30  # How close a wall needs to be, in cm, before we start turning
NUM_UNDERLIGHTS = 6  # Assuming the number of underlights

# Define sensor reading parameters
timeout = 50  # milliseconds
samples = 3  # number of readings for averaging
offset = 190000  # suitable for Raspberry Pi 4, adjust if necessary

# Define colors for underlighting
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# Add these constants near the top with your other constants
KNIGHT_RIDER_INTERVAL = 0.1
KNIGHT_RIDER_COLOR = RED
KNIGHT_RIDER_MAPPING = [
    LIGHT_REAR_LEFT,
    LIGHT_MIDDLE_LEFT,
    LIGHT_FRONT_LEFT,
    LIGHT_FRONT_RIGHT,
    LIGHT_MIDDLE_RIGHT,
    LIGHT_REAR_RIGHT
]

# Add these constants
BUTTON_DEBOUNCE_TIME = 0.3  # Time in seconds to wait between button presses
PARTY_MODE_INTERVAL = 0.2  # Time between color changes
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

# Add these at the top of your file with other global variables
knight_rider_active = False
party_mode_active = False

# Distance thresholds in cm
DANGER_DISTANCE = 20    # Red warning
CAUTION_DISTANCE = 40   # Yellow warning
SENSOR_READ_INTERVAL = 0.1  # How often to check distance (seconds)

def blink_underlights(trilobot, group, color, nr_cycles=DEFAULT_NUM_CYCLES, blink_rate_sec=DEFAULT_BLINK_RATE_SEC):
    for cy in range(nr_cycles):
        trilobot.set_underlights(group, color)
        sleep(blink_rate_sec)
        trilobot.clear_underlights(group)

# Function to show a startup animation on the underlights
def startup_animation():
    for led in range(NUM_UNDERLIGHTS):
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(led, RED)
        time.sleep(0.1)
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(led, GREEN)
        time.sleep(0.1)
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(led, BLUE)
        time.sleep(0.1)
    tbot.clear_underlighting()


# Complete project details at https://RandomNerdTutorials.com/raspberry-pi-mjpeg-streaming-web-server-picamera2/
# Mostly copied from https://picamera.readthedocs.io/en/release-1.13/recipes2.html
# Run this script, then point a web browser at http:<this-ip-address>:7123
# Note: needs simplejpeg to be installed (pip3 install simplejpeg).

PAGE = """\
<html>
<head>
<title>Trilobot Camera Stream</title>
</head>
<body>
<h1>Trilobot Camera Stream</h1>
<img src="stream.mjpg" width="640" height="480" />
</body>
</html>
"""

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging messages
        pass
        
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
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

def initialize_camera():
    try:
        picam2 = Picamera2()
        camera_config = picam2.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            lores={"size": (320, 240), "format": "YUV420"},
            display="lores"
        )
        picam2.configure(camera_config)
        return picam2
    except Exception as e:
        print(f"\rCamera initialization error: {str(e)}")
        return None

def cleanup_camera():
    try:
        # Kill any existing camera processes without camera service reset
        subprocess.run(['sudo', 'pkill', '-f', 'camera'], timeout=2)
        subprocess.run(['sudo', 'pkill', '-f', 'libcamera'], timeout=2)
        subprocess.run(['sudo', 'pkill', '-f', 'picamera2'], timeout=2)
        time.sleep(2)  # Give system time to clean up
    except Exception as e:
        print(f"Cleanup warning: {str(e)}")

def start_camera_stream():
    global picam2, output
    
    try:
        # Clean up first
        cleanup_camera()
        
        # Initialize camera
        picam2 = initialize_camera()
        if picam2 is None:
            print("\rFailed to initialize camera")
            return
        
        # Create output and start camera
        output = StreamingOutput()
        picam2.start()
        
        # Start encoder
        encoder = MJPEGEncoder(bitrate=10000000)
        picam2.start_recording(encoder, FileOutput(output))
        
        # Start server
        address = ('', 8000)
        server = StreamingServer(address, StreamingHandler)
        print(f"\rStreaming started - visit http://<IP-address>:8000")
        server.serve_forever()
        
    except Exception as e:
        print(f"\rStreaming setup error: {str(e)}")
    finally:
        if 'picam2' in locals():
            try:
                picam2.stop_recording()
                picam2.stop()
            except:
                pass

# Function to create and return a PS4 controller setup
def create_ps4_controller(stick_deadzone_percent=0.05):
    """Create a controller class for the PlayStation 4 Wireless controller."""
    print("\nAttempting to connect to PS4 controller...")
    
    try:
        # Create controller with basic setup, disable debug output
        controller = SimpleController("Wireless Controller", exact_match=True)
        controller.connect(debug=False)  # Disable connection debug messages
        
        if not controller.is_connected():
            return None

        print("Controller connected successfully!")
        
        # Register controls silently
        controller.register_button("Cross", 304)
        controller.register_button("Circle", 305)
        controller.register_button("Square", 308)
        controller.register_button("Triangle", 307)
        controller.register_button("Options", 315)
        controller.register_button("Share", 314)
        controller.register_button("PS", 316)
        controller.register_button("L1", 310)
        controller.register_button("L2", 312)
        controller.register_button("R1", 311)
        controller.register_button("R2", 313)
        controller.register_button("L3", 317)
        controller.register_button("R3", 318)
        
        # Register D-pad
        controller.register_axis_as_button("Left", 16, -1, 0)
        controller.register_axis_as_button("Right", 16, 1, 0)
        controller.register_axis_as_button("Up", 17, -1, 0)
        controller.register_axis_as_button("Down", 17, 1, 0)
        
        # Register analog sticks with reduced deadzone and optimized ranges
        controller.register_axis("LX", 0, 0, 255, deadzone_percent=stick_deadzone_percent)
        controller.register_axis("LY", 1, 0, 255, deadzone_percent=stick_deadzone_percent)
        controller.register_axis("RX", 3, 0, 255, deadzone_percent=stick_deadzone_percent)
        controller.register_axis("RY", 4, 0, 255, deadzone_percent=stick_deadzone_percent)
        controller.register_axis("L2", 2, 0, 255)
        controller.register_axis("R2", 5, 0, 255)
        
        return controller
        
    except Exception as e:
        print(f"Controller initialization error: {str(e)}")
        return None

# Function to sense the environment using the ultrasonic sensor
def sense_environment(last_distance, threshold, timeout, samples, offset):
    try:
        distance = tbot.read_distance(timeout=timeout, samples=samples, offset=offset)
        if abs(distance - last_distance) > threshold:
            tbot.set_underlight(LIGHT_FRONT_LEFT, 0, 255, 0, show=False)
            tbot.set_underlight(LIGHT_FRONT_RIGHT, 0, 255, 0, show=False)
        return distance
    except Exception:
        return last_distance  # Return last known distance instead of printing error

# Function to handle obstacle detection and avoidance
def handle_obstacles(distance):
    if distance > 0 and distance < 20:
        tbot.set_underlight(LIGHT_FRONT_LEFT, 255, 0, 0, show=False)      # Red
        tbot.set_underlight(LIGHT_FRONT_RIGHT, 255, 0, 0, show=False)      # Red
    else:
        tbot.set_underlight(LIGHT_FRONT_LEFT, 0, 0, 0, show=False)      # Black
        tbot.set_underlight(LIGHT_FRONT_RIGHT, 0, 0, 0, show=False)      # Black

# Function to handle motor control based on controller input
def handle_motor_control(controller, tank_steer):
    try:
        if tank_steer:
            # Tank steering mode (each stick controls one side)
            ly = controller.read_axis("LY")
            ry = controller.read_axis("RY")
            
            # Apply exponential curve for finer control at low speeds
            ly = math.copysign(ly * ly, ly)
            ry = math.copysign(ry * ry, ry)
            
            tbot.set_left_speed(-ly)
            tbot.set_right_speed(-ry)
        else:
            # Normal steering mode (left stick for both motors)
            lx = controller.read_axis("LX")
            ly = -controller.read_axis("LY")  # Inverted for intuitive control
            
            # Apply exponential curve for finer control
            lx = math.copysign(lx * lx, lx)
            ly = math.copysign(ly * ly, ly)
            
            # Calculate motor speeds with improved turning
            left_speed = ly + (lx * 0.7)  # Reduced turning sensitivity
            right_speed = ly - (lx * 0.7)
            
            # Ensure speeds don't exceed limits
            left_speed = max(min(left_speed, 1.0), -1.0)
            right_speed = max(min(right_speed, 1.0), -1.0)
            
            tbot.set_left_speed(left_speed)
            tbot.set_right_speed(right_speed)
            
    except ValueError:
        tbot.disable_motors()

def handle_controller_input(controller, tank_steer, button_states):
    global knight_rider_active, party_mode_active
    current_time = time.time()
    
    try:
        # Tank steer toggle
        if controller.read_button("L1") and tank_steer:
            tank_steer = False
            print("\rTank Steering Disabled ")
        elif controller.read_button("R1") and not tank_steer:
            tank_steer = True
            print("\rTank Steering Enabled  ")

        # Handle Cross button with debouncing (Button LEDs)
        if controller.read_button("Cross"):
            if not button_states['cross_pressed'] and (current_time - button_states['last_cross_time']) > BUTTON_DEBOUNCE_TIME:
                button_states['cross_pressed'] = True
                button_states['last_cross_time'] = current_time
                # Toggle button LEDs
                button_states['button_leds_on'] = not button_states['button_leds_on']
                for led in range(NUM_BUTTONS):
                    tbot.set_button_led(led, button_states['button_leds_on'])
        else:
            button_states['cross_pressed'] = False

        # Handle Square button with debouncing (Knight Rider effect)
        if controller.read_button("Square"):
            if not button_states['square_pressed'] and (current_time - button_states['last_square_time']) > BUTTON_DEBOUNCE_TIME:
                button_states['square_pressed'] = True
                button_states['last_square_time'] = current_time
                knight_rider_active = not knight_rider_active
                if knight_rider_active:
                    party_mode_active = False
                if not knight_rider_active:
                    tbot.clear_underlighting()
        else:
            button_states['square_pressed'] = False

        # Handle Triangle button with debouncing (Party Mode)
        if controller.read_button("Triangle"):
            if not button_states['triangle_pressed'] and (current_time - button_states['last_triangle_time']) > BUTTON_DEBOUNCE_TIME:
                button_states['triangle_pressed'] = True
                button_states['last_triangle_time'] = current_time
                party_mode_active = not party_mode_active
                if party_mode_active:
                    knight_rider_active = False
                if not party_mode_active:
                    tbot.clear_underlighting()
        else:
            button_states['triangle_pressed'] = False

        # Handle Circle button with debouncing
        if controller.read_button("Circle"):
            if not button_states['circle_pressed'] and (current_time - button_states['last_circle_time']) > BUTTON_DEBOUNCE_TIME:
                button_states['circle_pressed'] = True
                button_states['last_circle_time'] = current_time
                capture_image_with_raspistill()
        else:
            button_states['circle_pressed'] = False

    except ValueError:
        pass

    return tank_steer, button_states

def function_for_triangle_button():
    print("Triangle button function activated")
    tbot.set_underlight(LIGHT_FRONT_LEFT, 255, 0, 0, show=False)      # Red

def function_for_square_button():
    print("Square button function activated")
    tbot.set_underlight(LIGHT_REAR_LEFT, 0, 255, 0, show=False)       # Green

def function_for_cross_button():
    print("Cross button function activated")
    tbot.set_underlight(LIGHT_REAR_RIGHT, 0, 255, 255, show=False)    # Cyan

def function_for_share_button():
    print("Share button function activated")
    tbot.set_underlight(LIGHT_FRONT_RIGHT, 255, 0, 255, show=False)   # Magenta

# Function to handle underlighting animation based on controller connection
def handle_underlighting(h, v, controller_connected):
    if controller_connected:
        for led in range(NUM_UNDERLIGHTS):
            led_h = h + (led * (1.0 / NUM_UNDERLIGHTS))
            if led_h >= 1.0:
                led_h -= 1.0
            tbot.set_underlight_hsv(led, led_h, show=False)
        tbot.show_underlighting()
        h += 0.5 / 360
        if h >= 1.0:
            h -= 1.0
    else:
        val = (math.sin(v) / 2.0) + 0.5
        tbot.fill_underlighting(int(val * 127), 0, 0)
        v += math.pi / 200
    return h, v

# Add this function to handle the Knight Rider effect
def update_knight_rider_lights(current_led, direction):
    """Updates the Knight Rider light effect"""
    tbot.clear_underlighting(show=False)
    tbot.set_underlight(KNIGHT_RIDER_MAPPING[current_led], KNIGHT_RIDER_COLOR)
    
    # Update position for next frame
    if direction == 1:  # Moving right
        if current_led >= NUM_UNDERLIGHTS - 1:
            return current_led - 1, -1  # Start moving left
        return current_led + 1, 1
    else:  # Moving left
        if current_led <= 0:
            return current_led + 1, 1  # Start moving right
        return current_led - 1, -1

def update_party_lights(current_color_index):
    """Updates the party mode lights"""
    color = PARTY_COLORS[current_color_index]
    # Alternate between all lights and every other light
    if current_color_index % 2 == 0:
        # All lights same color
        tbot.clear_underlighting(show=False)
        for light in range(6):  # 0 to 5 for all lights
            tbot.set_underlight(light, *color, show=False)
        tbot.show_underlighting()
    else:
        # Alternating lights
        tbot.clear_underlighting(show=False)
        for light in range(0, 6, 2):  # Every other light (0, 2, 4)
            tbot.set_underlight(light, *color, show=False)
        tbot.show_underlighting()
    
    # Move to next color
    return (current_color_index + 1) % len(PARTY_COLORS)

def handle_distance_warning(distance):
    """Updates front underlights based on distance"""
    if distance > 0:  # Valid reading
        if distance < DANGER_DISTANCE:
            # Close - Red warning
            tbot.set_underlight(LIGHT_FRONT_LEFT, 255, 0, 0, show=False)
            tbot.set_underlight(LIGHT_FRONT_RIGHT, 255, 0, 0, show=False)
        elif distance < CAUTION_DISTANCE:
            # Medium distance - Yellow warning
            tbot.set_underlight(LIGHT_FRONT_LEFT, 255, 255, 0, show=False)
            tbot.set_underlight(LIGHT_FRONT_RIGHT, 255, 255, 0, show=False)
        else:
            # Far - Lights off
            tbot.set_underlight(LIGHT_FRONT_LEFT, 0, 0, 0, show=False)
            tbot.set_underlight(LIGHT_FRONT_RIGHT, 0, 0, 0, show=False)
    tbot.show_underlighting()

# Main function
def main():
    global stream_process, knight_rider_active, party_mode_active
    
    # Initialize light effect variables
    knight_rider_led = 0
    knight_rider_direction = 1
    party_color_index = 0
    last_knight_rider_update = time.time()
    last_party_update = time.time()
    
    # Initialize button states
    button_states = {
        'square_pressed': False,
        'last_square_time': 0,
        'triangle_pressed': False,
        'last_triangle_time': 0,
        'circle_pressed': False,
        'last_circle_time': 0,
        'cross_pressed': False,
        'last_cross_time': 0,
        'button_leds_on': False
    }
    
    # Make sure button LEDs start off
    for led in range(NUM_BUTTONS):
        tbot.set_button_led(led, False)
    
    # Clean up any existing camera processes first
    cleanup_camera()
    
    # Initialize distance sensor variables
    last_sensor_read = time.time()
    
    try:
        # Start the camera stream in a separate process
        stream_process = Process(target=start_camera_stream)
        stream_process.start()
        time.sleep(3)
        
        startup_animation()
        
        # Initialize controller
        controller = create_ps4_controller()
        if controller is None:
            raise Exception("Controller connection failed")
        
        print("\nController connected and ready!")
        tank_steer = False
        
        # Main control loop
        while True:
            try:
                current_time = time.time()
                
                # Update controller
                controller.update(debug=False)
                tank_steer, button_states = handle_controller_input(
                    controller, tank_steer, button_states
                )
                handle_motor_control(controller, tank_steer)
                
                # Read distance sensor periodically if not in a light show mode
                if not (knight_rider_active or party_mode_active):
                    if current_time - last_sensor_read >= SENSOR_READ_INTERVAL:
                        distance = tbot.read_distance(timeout=50, samples=3)
                        handle_distance_warning(distance)
                        last_sensor_read = current_time
                
                # Update light effects
                if knight_rider_active and (current_time - last_knight_rider_update) >= KNIGHT_RIDER_INTERVAL:
                    knight_rider_led, knight_rider_direction = update_knight_rider_lights(
                        knight_rider_led, knight_rider_direction
                    )
                    last_knight_rider_update = current_time
                
                if party_mode_active and (current_time - last_party_update) >= PARTY_MODE_INTERVAL:
                    party_color_index = update_party_lights(party_color_index)
                    last_party_update = current_time
                
            except Exception as e:
                print(f"\rController error: {str(e)}")
                time.sleep(1)
                controller = create_ps4_controller()
                if controller is None:
                    print("\rAttempting to reconnect...", end='')
            
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    except Exception as e:
        print(f"\nProgram error: {str(e)}")
    finally:
        if 'stream_process' in globals():
            stream_process.terminate()
            stream_process.join(timeout=1)
            if stream_process.is_alive():
                stream_process.kill()
        cleanup_camera()
        tbot.clear_underlighting()
        tbot.disable_motors()
        # Turn off all button LEDs when program ends
        for led in range(NUM_BUTTONS):
            tbot.set_button_led(led, False)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    finally:
        # Ensure cleanup happens even if program crashes
        if 'stream_process' in globals():
            stream_process.terminate()
            stream_process.join(timeout=1)
            if stream_process.is_alive():
                stream_process.kill()
        cleanup_camera()
        tbot.clear_underlighting()
        tbot.disable_motors()

