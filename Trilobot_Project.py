from trilobot import Trilobot, controller_mappings, BUTTON_A, LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_RIGHT
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
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
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


picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
output = StreamingOutput()
encoder = MJPEGEncoder()
picam2.start_recording(encoder, FileOutput(output))

try:
    address = ('', 7123)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    picam2.stop_recording()

# Function to create and return a PS4 controller setup
def create_ps4_controller(stick_deadzone_percent=0.1):
    """ Create a controller class for the PlayStation 4 Wireless controller.
    stick_deadzone_percent: the deadzone amount to apply to the controller's analog sticks
    """
    controller = SimpleController("Wireless Controller", exact_match=True)

    # Button and axis registrations for PS4 Controller
    controller.register_button("Cross", 304, alt_name="A")
    controller.register_button("Circle", 305, alt_name="B")
    controller.register_button("Square", 308, alt_name="X")
    controller.register_button("Triangle", 307, alt_name="Y")
    controller.register_button("Options", 315, alt_name='Start')
    controller.register_button("Share", 314, alt_name='Select')
    controller.register_button("PS", 316, alt_name='Home')
    controller.register_button("L1", 310, alt_name="LB")
    controller.register_button("L2", 312, alt_name="LT")
    controller.register_button("R1", 311, alt_name="RB")
    controller.register_button("R2", 313, alt_name="RT")
    controller.register_axis_as_button("Left", 16, -1, 0)
    controller.register_axis_as_button("Right", 16, 1, 0)
    controller.register_axis_as_button("Up", 17, -1, 0)
    controller.register_axis_as_button("Down", 17, 1, 0)
    controller.register_button("L3", 317, alt_name='LS')
    controller.register_button("R3", 318, alt_name='RS')

    controller.register_axis("LX", 0, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("LY", 1, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RX", 3, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RY", 4, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_trigger_axis("L2", 2, 0, 255, alt_name="LT")
    controller.register_trigger_axis("R2", 5, 0, 255, alt_name="RT")
    return controller

# Function to sense the environment using the ultrasonic sensor
def sense_environment(last_distance, threshold, timeout, samples, offset):
    distance = tbot.read_distance(timeout=timeout, samples=samples, offset=offset)
    if abs(distance - last_distance) > threshold:
        tbot.set_underlight(LIGHT_FRONT_LEFT, 0, 255, 0, show=False)      # Green
        tbot.set_underlight(LIGHT_FRONT_RIGHT, 0, 255, 0, show=False)      # Green
    return distance

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
            ly = controller.read_axis("LY")
            ry = controller.read_axis("RY")
            tbot.set_left_speed(-ly)
            tbot.set_right_speed(-ry)
        else:
            lx = controller.read_axis("LX")
            ly = 0 - controller.read_axis("LY")
            tbot.set_left_speed(ly + lx)
            tbot.set_right_speed(ly - lx)
    except ValueError:
        tbot.disable_motors()

def handle_controller_input(controller, tank_steer, button_pressed_last_frame):
    try:
        if controller.read_button("L1") and tank_steer:
            tank_steer = False
            print("Tank Steering Disabled")
        elif controller.read_button("R1") and not tank_steer:
            tank_steer = True
            print("Tank Steering Enabled")

        if controller.read_button("Circle") and not button_pressed_last_frame:
            print("Circle button pressed - Capturing image")
            capture_image_with_raspistill()
            button_pressed_last_frame = True
        elif controller.read_button("Square"):
            print("Square button pressed")
            function_for_square_button()
        elif controller.read_button("Triangle"):
            print("Triangle button pressed")
            function_for_triangle_button()
        elif controller.read_button("Cross"):
            print("Cross button pressed")
            function_for_cross_button()
        else:
            button_pressed_last_frame = False

    except ValueError:
        print("Button not available or error in reading button state")

    return tank_steer, button_pressed_last_frame

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

# Streaming server setup
PAGE = """\
<html>
<head>
<title>Raspberry Pi - Camera Stream</title>
</head>
<body>
<h1>Raspberry Pi - Camera Stream</h1>
<img src="stream.mjpg" width="640" height="480" />
</body>
</html>
"""

class StreamingOutput(object):
    def __init__(self):
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = Condition()

    def write(self, buf):
        if buf.startswith(b'\xff\xd8'):
            # New frame, copy the existing buffer's content and notify all clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
        return self.buffer.write(buf)

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(PAGE.encode('utf-8'))
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
                    "Removed streaming client %s: %s",
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def start_streaming():
    global output
    try:
        address = ('', 8000)
        server = StreamingServer(address, StreamingHandler)
        print("Starting server at http://<Raspberry_Pi_IP_Address>:8000")
        server.serve_forever()
    finally:
        picam2.stop_recording()

# Main function
def main():
    startup_animation()

    # Start streaming in a separate process
    streaming_process = Process(target=start_streaming)
    streaming_process.start()

    # Initialize the PS4 controller
    controller = create_ps4_controller()

    button_pressed_last_frame = False
    tank_steer = False
    last_distance = 0

    h = 0
    v = 0

    while True:
        if not controller.is_connected():
            controller.reconnect(10, True)

        distance = sense_environment(last_distance, threshold=5, timeout=timeout, 
                                  samples=samples, offset=offset)
        handle_obstacles(distance)
        last_distance = distance

        try:
            controller.update()
        except RuntimeError:
            tbot.disable_motors()

        if controller.is_connected():
            tank_steer, button_pressed_last_frame = handle_controller_input(
                controller, tank_steer, button_pressed_last_frame
            )
            handle_motor_control(controller, tank_steer)

            h, v = handle_underlighting(h, v, True)
        else:
            h, v = handle_underlighting(h, v, False)

        time.sleep(0.01)

if __name__ == "__main__":
    main()

