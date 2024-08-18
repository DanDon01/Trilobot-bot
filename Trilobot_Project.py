from trilobot import Trilobot, controller_mappings
from trilobot.simple_controller import SimpleController
import picamera
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

# Initialize the Trilobot
tbot = Trilobot()

NUM_UNDERLIGHTS = 6  # Assuming the number of underlights

# Define sensor reading parameters
timeout = 100  # milliseconds
samples = 5  # number of readings for averaging
offset = 190000  # suitable for Raspberry Pi 4, adjust if necessary

# Define colors for underlighting
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

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

def capture_image_with_raspistill():
    try:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        image_path = f"/home/pi/captured_image_{timestamp}.jpg"
        command = ["raspistill", "-o", image_path, "-t", "2000", "-q", "100"]
        subprocess.run(command, check=True)
        print(f"Image captured and saved to {image_path}")
    except Exception as e:
        print(f"Error capturing image: {e}")

# Function to create and return a PS4 controller setup
def create_ps4_controller(stick_deadzone_percent=0.1):
    controller = SimpleController("Wireless Controller", exact_match=True)
    controller.register_button("Circle", 305, alt_name="B")
    controller.register_axis("LX", 0, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("LY", 1, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RX", 3, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RY", 4, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_trigger_axis("L2", 2, 0, 255, alt_name="LT")
    controller.register_trigger_axis("R2", 5, 0, 255, alt_name="RT")
    controller.register_button("Triangle", 307, alt_name="Y")
    controller.register_button("Square", 304, alt_name="X")
    controller.register_button("Cross", 306, alt_name="A")
    controller.register_button("Share", 314, alt_name="Back")
    return controller

# Function to sense the environment using the ultrasonic sensor
def sense_environment(last_distance, threshold=10, timeout=100, samples=5, offset=190000):
    distance = tbot.read_distance(timeout=timeout, samples=samples, offset=offset)
    if abs(distance - last_distance) > threshold:
        print(f"Distance changed: {distance} cm")
    return distance

# Function to handle obstacle detection and avoidance
def handle_obstacles(distance):
    if distance > 0 and distance < 20:
        print("Obstacle detected. Making adjustments.")
        # Implement obstacle avoidance logic here
    else:
        print("Path clear. Continuing forward.")
        # Implement clear path logic here

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
    # Add your functionality here

def function_for_square_button():
    print("Square button function activated")
    # Add your functionality here

def function_for_cross_button():
    print("Cross button function activated")
    # Add your functionality here

def function_for_share_button():
    print("Share button function activated")
    # Add your functionality here

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
    with picamera.PiCamera(resolution='640x480', framerate=24) as camera:
        global output
        output = StreamingOutput()
        camera.start_recording(output, format='mjpeg')
        try:
            address = ('', 8000)
            server = StreamingServer(address, StreamingHandler)
            print("Starting server at http://<Raspberry_Pi_IP_Address>:8000")
            server.serve_forever()
        finally:
            camera.stop_recording()

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

        distance = sense_environment(last_distance)
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

