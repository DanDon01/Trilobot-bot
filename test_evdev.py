# test_evdev.py
import sys
import time # Added for potential sleep
from evdev import InputDevice, categorize, ecodes, list_devices

# --- Change this if your controller path might change ---
DEVICE_PATH = "/dev/input/event9"
# -----------------------------------------------------

print(f"Attempting to open device: {DEVICE_PATH}")
device = None # Initialize device variable

try:
    # Try opening the device
    device = InputDevice(DEVICE_PATH)
    print(f"Successfully opened: {device.name}")
    print(f"Device capabilities: {device.capabilities(verbose=True)}") # Print capabilities
    print("\nEntering event read loop (press Ctrl+C to exit)...")
    print("Please press buttons or move sticks on the controller.\n")

    # Try the non-blocking read loop first
    while True:
        event = device.read_one()
        if event is not None:
            print(f"Event (read_one): type={event.type}, code={event.code}, value={event.value}")
        else:
            # Optional: uncomment to see if the loop is just spinning
            # print(".", end="", flush=True)
            time.sleep(0.01) # Small sleep to prevent high CPU usage

except FileNotFoundError:
    print(f"ERROR: Device not found at {DEVICE_PATH}", file=sys.stderr)
    print("Please ensure the controller is connected and the path is correct.", file=sys.stderr)
    sys.exit(1)
except PermissionError:
    print(f"ERROR: Permission denied for {DEVICE_PATH}", file=sys.stderr)
    print("Try running this script with 'sudo'.", file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    print("\nExiting loop.")
except Exception as e:
    print(f"\nAn unexpected error occurred during read: {e}", file=sys.stderr)
finally:
    if device:
        try:
            device.close()
            print("Device closed.")
        except Exception as e:
            print(f"Error closing device: {e}", file=sys.stderr)

print("Script finished.")