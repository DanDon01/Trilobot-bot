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

# Run an amination on the underlights to show a controller has been selected
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
    # Define the path and name for the output image
    image_path = "/home/pibot/captured_image.jpg"
    
    # Define the raspistill command with desired options
    command = ["raspistill", "-o", image_path, "-t", "2000", "-q", "100"]
    
    # Execute the command
    subprocess.run(command, check=True)
    
    print(f"Image captured and saved to {image_path}")


# Function to capture an image
def capture_image():
    with picamera.PiCamera() as camera:
        camera.resolution = (1024, 768)  # Set resolution
        camera.capture('/home/pibot/trilobot_image.jpg')  # Save image
        print("Image captured.")

# Function to create and return a PS4 controller setup
def create_ps4_controller(stick_deadzone_percent=0.1):
    controller = SimpleController("Wireless Controller", exact_match=True)
    # Button and axis registration for PS4 controller
    # This should mirror the setup you'd like for your PS4 controller based on the provided examples
    # Add your button and axis registrations here following the example
    controller.register_button("Circle", 305, alt_name="B")
    controller.register_axis("LX", 0, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("LY", 1, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RX", 3, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_axis("RY", 4, 0, 255, deadzone_percent=stick_deadzone_percent)
    controller.register_trigger_axis("L2", 2, 0, 255, alt_name="LT")
    controller.register_trigger_axis("R2", 5, 0, 255, alt_name="RT")
    return controller

def sense(tbot, timeout=100, samples=5, offset=190000):
    while True:
    # Read distance from the ultrasonic sensor
        distance = tbot.read_distance(timeout=timeout, samples=samples, offset=offset)
    
    if distance > 0:
        print(f"Distance: {distance} cm")
        # If the path is clear, continue moving forward
        # Adjust your movement code here
    else:
         print("No valid reading or obstacle too close. Adjusting route...")
        # Implement obstacle avoidance or turning logic here

    # Implement your mapping logic by updating a map representation based on distance readings
    
    # Small delay to prevent too rapid execution
    return distance

def main():
    # Create the PS4 controller
    controller = create_ps4_controller()
    controller.update()
    
    button_pressed_last_frame = False
    
    h = 0
    v = 0
    spacing = 1.0 / NUM_UNDERLIGHTS
    tank_steer = False
    
    while True:
        if not controller.is_connected():
            controller.reconnect(10, True)

        if distance > 0 and distance < 20:
            print("Obstacle detected. Making adjustments.")
            # Implement obstacle detection logic
        else:
            print("Path clear. Continuing forward.")
            # Implement clear path logic

        try:
            controller.update()
        except RuntimeError:
            tbot.disable_motors()

        if controller.is_connected():
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

            # Check if the 'A' button is pressed to capture an image
            try:
    # Check if the button is currently pressed
                is_button_pressed = controller.read_button("Circle")
    
    # If the button was not pressed last frame but is pressed now, capture an image
                if is_button_pressed and not button_pressed_last_frame:
                    capture_image_with_raspistill()
                    time.sleep(1)  # Prevent multiple captures
    
    # Update the last known button state for the next iteration
                    button_pressed_last_frame = is_button_pressed
    
            except ValueError:
                  print("Capture button not available")


            # Underlight animation for visual feedback
            for led in range(NUM_UNDERLIGHTS):
                led_h = h + (led * spacing)
                if led_h >= 1.0:
                    led_h -= 1.0
                tbot.set_underlight_hsv(led, led_h, show=False)
            tbot.show_underlighting()

            h += 0.5 / 360
            if h >= 1.0:
                h -= 1.0
        else:
            # Slow red pulsing animation to indicate no controller connection
            val = (math.sin(v) / 2.0) + 0.5
            tbot.fill_underlighting(int(val * 127), 0, 0)
            v += math.pi / 200

        time.sleep(0.01)

       
if __name__ == "__main__":
    main()
