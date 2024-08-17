from trilobot import Trilobot, controller_mappings
from trilobot.simple_controller import SimpleController
import picamera
import subprocess
import time
import math

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

# Function to capture an image using the PiCamera
def capture_image():
    with picamera.PiCamera() as camera:
        camera.resolution = (1024, 768)  # Set resolution
        camera.capture('/home/pibot/trilobot_image.jpg')  # Save image
        print("Image captured.")

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
    return controller

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

# Main function
def main():
    startup_animation()
    
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
