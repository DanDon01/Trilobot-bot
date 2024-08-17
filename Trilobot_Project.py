from trilobot import Trilobot, controller_mappings
from trilobot.simple_controller import SimpleController
import picamera
import subprocess
import time
import math
import io
import logging
import socketserver
from threading import Condition, Thread
from http import server

# Initialize the Trilobot
tbot = Trilobot()

NUM_UNDERLIGHTS = 5  # Assuming the number of underlights

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

# Function to capture an image using raspistill
def capture_image_with_raspistill():
    image_path = "/home/pibot/captured_image.jpg"
    command = ["raspistill", "-o", image_path, "-t", "2000", "-q", "100"]
    subprocess.run(command, check=True)
    print(f"Image captured and saved to {image_path}")

# Function to sense the environment using the ultrasonic sensor
def sense_environment(timeout=100, samples=5, offset=190000):
    distance = tbot.read_distance(timeout=timeout, samples=samples, offset=offset)
    if distance > 0:
        print(f"Distance: {distance} cm")
    else:
        print("No valid reading or obstacle too close. Adjusting route...")
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

# Function to handle controller input and toggle tank steering mode
def handle_controller_input(controller, tank_steer, button_pressed_last_frame):
    try:
        if controller.read_button("L1") and tank_steer:
            tank_steer = False
            print("Tank Steering Disabled")
        elif controller.read_button("R1") and not tank_steer:
            tank_steer = True
            print("Tank Steering Enabled")
    except ValueError:
        print("Tank Steering Not Available")

    try:
        is_button_pressed = controller.read_button("Circle")
        if is_button_pressed and not button_pressed_last_frame:
            capture_image_with_raspistill()
            time.sleep(1)  # Prevent multiple captures
        button_pressed_last_frame = is_button_pressed
    except ValueError:
        print("Capture button not available")

    return tank_steer, button_pressed_last_frame

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

    # Start streaming in a separate thread
    streaming_thread = Thread(target=start_streaming)
    streaming_thread.start()

    controller = create_ps4_controller()
    controller.update()

    button_pressed_last_frame = False
    tank_steer = False

    h = 0
    v = 0

    while True:
        if not controller.is_connected():
            controller.reconnect(10, True)

        distance = sense_environment()
        handle_obstacles(distance)

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
