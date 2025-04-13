"""
PS4 Controller Module for Trilobot

This module handles the PS4 controller input for controlling the Trilobot.
It maps controller buttons and joysticks to robot actions.
"""

import threading
import time
import logging
import subprocess
import os
from math import copysign

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker, log_debug
from config import config
from control_manager import control_manager, ControlMode, ControlAction

logger = logging.getLogger('trilobot.ps4')

# Try to import evdev for controller input
try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    logger.warning("Evdev module not available. PS4 controller support disabled.")

class PS4Controller:
    """Handler for PS4 controller input"""
    
    def __init__(self):
        self.device = None
        self.running = False
        self.input_thread = None
        self.stop_input = threading.Event()
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.bluetooth_connected = False
        self.web_only_mode = False
        
        # Controller state
        self.buttons = {}
        self.axes = {
            'left_x': 0,   # Left stick X: -1 (left) to 1 (right)
            'left_y': 0,   # Left stick Y: -1 (up) to 1 (down)
            'right_x': 0,  # Right stick X: -1 (left) to 1 (right)
            'right_y': 0,  # Right stick Y: -1 (up) to 1 (down)
            'l2': 0,       # L2 trigger: 0 to 1
            'r2': 0        # R2 trigger: 0 to 1
        }
        
        # Control settings
        self.deadzone = config.get("movement", "stick_deadzone")
        self.max_speed = config.get("movement", "max_speed")
        
        # Button mapping (for PS4 controller using evdev)
        self.button_map = {
            304: 'x',          # X button
            305: 'circle',     # Circle button
            307: 'triangle',   # Triangle button
            308: 'square',     # Square button
            310: 'l1',         # L1 button
            311: 'r1',         # R1 button
            312: 'l2_button',  # L2 button (press, not analog)
            313: 'r2_button',  # R2 button (press, not analog)
            314: 'share',      # Share button
            315: 'options',    # Options button
            316: 'ps',         # PS button
            317: 'l3',         # L3 button (left stick press)
            318: 'r3',         # R3 button (right stick press)
        }
        
        # Axis mapping
        self.axis_map = {
            0: 'left_x',      # Left stick X
            1: 'left_y',      # Left stick Y
            2: 'l2',          # L2 trigger
            3: 'right_x',     # Right stick X
            4: 'right_y',     # Right stick Y
            5: 'r2',          # R2 trigger
            16: 'dpad_x',     # D-pad X
            17: 'dpad_y'      # D-pad Y
        }
        
        log_info("PS4 Controller initialized")
    
    def check_bluetooth_status(self):
        """Check if Bluetooth is enabled and working"""
        try:
            # Check if bluetoothctl is available and bluetooth service is running
            result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                                    capture_output=True, text=True, check=False)
            
            if result.stdout.strip() == 'active':
                log_info("Bluetooth service is active")
                
                # Check for available Bluetooth devices
                bt_result = subprocess.run(['bluetoothctl', 'devices'], 
                                          capture_output=True, text=True, check=False)
                
                if "controller" in bt_result.stderr.lower():
                    log_warning("Bluetooth controller not available")
                    return False
                    
                # Look for PlayStation or DualShock in device list
                ps_devices = [line for line in bt_result.stdout.split('\n') 
                             if 'dual' in line.lower() or 'playstation' in line.lower() or 'ps4' in line.lower()]
                
                if ps_devices:
                    log_info(f"Found PS4 controller devices in Bluetooth: {ps_devices}")
                    return True
                else:
                    log_warning("No PS4 controller found in paired Bluetooth devices")
                    # Try to scan for new devices
                    log_info("Scanning for Bluetooth devices...")
                    scan_result = subprocess.run(['bluetoothctl', 'scan', 'on'], 
                                                capture_output=True, text=True, timeout=5, check=False)
                    return False
            else:
                log_warning("Bluetooth service is not active")
                return False
                
        except Exception as e:
            log_error(f"Error checking Bluetooth status: {e}")
            return False
    
    def attempt_bluetooth_connection(self):
        """Attempt to connect to the PS4 controller via Bluetooth"""
        if self.connection_attempts >= self.max_connection_attempts:
            log_warning(f"Maximum connection attempts ({self.max_connection_attempts}) reached")
            return False
            
        self.connection_attempts += 1
        
        try:
            log_info(f"Bluetooth connection attempt {self.connection_attempts}/{self.max_connection_attempts}")
            
            # Check if Bluetooth is enabled
            if not self.check_bluetooth_status():
                log_warning("Bluetooth not properly configured")
                return False
                
            # Look for PS4 controller using evdev
            found = self.find_controller()
            if found:
                self.bluetooth_connected = True
                self.connection_attempts = 0  # Reset counter on successful connection
                log_info("Successfully connected to PS4 controller via Bluetooth")
                return True
                
            log_warning("Could not connect to PS4 controller via Bluetooth")
            return False
            
        except Exception as e:
            log_error(f"Error attempting Bluetooth connection: {e}")
            return False
    
    def find_controller(self):
        """Find PS4 controller device"""
        if not EVDEV_AVAILABLE:
            log_error("Evdev module not available. Cannot find PS4 controller.")
            return False
            
        try:
            # Search for PS4 controller in available devices
            devices_found = []
            
            for device_path in list_devices():
                try:
                    device = InputDevice(device_path)
                    devices_found.append((device, device_path))
                    
                    # Look for PS4 controller keywords in the device name
                    if ("sony" in device.name.lower() or 
                        "playstation" in device.name.lower() or 
                        "wireless controller" in device.name.lower() or
                        "dualshock" in device.name.lower()):
                        self.device = device
                        log_info(f"Found PS4 controller: {device.name} at {device_path}")
                        return True
                except Exception as e:
                    log_warning(f"Error checking device {device_path}: {e}")
                    continue
            
            # If no devices found, log the available devices
            if devices_found:
                log_warning(f"No PS4 controller found automatically. Found {len(devices_found)} input devices.")
                # If we have devices but none matched the PS4 keywords, let the user select
                return self._prompt_manual_device_selection(devices_found)
            else:
                log_warning("No input devices found")
                
            return False
        except Exception as e:
            log_error(f"Error finding PS4 controller: {e}")
            return False
    
    def _prompt_manual_device_selection(self, devices):
        """Prompt user to manually select an input device"""
        print("\n====== MANUAL CONTROLLER SELECTION ======")
        print("No PS4 controller was detected automatically.")
        print("Available input devices:")
        
        for i, (device, path) in enumerate(devices):
            print(f"{i+1}. {device.name} (at {path})")
        
        # Adjust numbering for clarity
        print(f"{len(devices)+1}. None of these - continue without controller (or just press Enter)")
        print("=========================================")
        
        try:
            choice_str = input(f"\nSelect device number [1-{len(devices)}] (or Enter/0 for none): ").strip()
            
            if not choice_str or choice_str == '0': # Handle Enter or 0
                print("No device selected. Continuing without PS4 controller.")
                self.web_only_mode = True # Explicitly set web only mode
                return False
            
            choice = int(choice_str)
            if 1 <= choice <= len(devices):
                selected_device, _ = devices[choice-1]
                self.device = selected_device
                print(f"Selected: {selected_device.name}")
                return True
            else:
                print("Invalid choice number.")
                self.web_only_mode = True
                return False
        except ValueError:
            print("Invalid input (not a number). Continuing without PS4 controller.")
            self.web_only_mode = True
            return False
        except KeyboardInterrupt:
            print("\nSelection cancelled. Continuing without controller.")
            self.web_only_mode = True
            return False
        except Exception as e:
            print(f"Error in selection: {e}")
            self.web_only_mode = True
            return False
    
    def display_connection_instructions(self):
        """Display instructions for connecting a PS4 controller"""
        print("\n====== PS4 CONTROLLER CONNECTION ======")
        print("No PS4 controller detected. Follow these steps to connect:")
        print("")
        print("1. Put your PS4 controller in pairing mode:")
        print("   - Press and hold the SHARE button")
        print("   - While holding SHARE, press and hold the PS button")
        print("   - The light bar will start flashing rapidly when in pairing mode")
        print("")
        print("2. On the Raspberry Pi, run these commands in a separate terminal:")
        print("   $ sudo bluetoothctl")
        print("   [bluetooth]# agent on")
        print("   [bluetooth]# default-agent")
        print("   [bluetooth]# scan on")
        print("   (Wait for 'Wireless Controller' to appear)")
        print("   [bluetooth]# pair XX:XX:XX:XX:XX:XX (replace with your controller's address)")
        print("   [bluetooth]# trust XX:XX:XX:XX:XX:XX")
        print("   [bluetooth]# connect XX:XX:XX:XX:XX:XX")
        print("")
        print("Waiting for controller connection... (Press Ctrl+C to continue without controller)")
        print("=======================================\n")
    
    def prompt_web_only_mode(self):
        """
        Prompts about continuing in web-only mode
        Returns True if the application should continue, False if it should exit
        """
        log_warning("PS4 controller not found after multiple attempts")
        
        # Check if we should skip the prompt based on config
        if config.get("development", "skip_hardware_check"):
            print("\nSkipping PS4 controller prompt due to configuration")
            self.web_only_mode = True
            state_tracker.update_state('control_mode', 'web_only')
            return True
        
        print("\n====== CONTROLLER NOT DETECTED ======")
        print("No PS4 controller found. You have these options:")
        print("1. Continue with Web Controls only")
        print("2. Exit the program and try again")
        print("")
        
        try:
            user_choice = input("Enter your choice (1 or 2): ").strip()
            if user_choice == "2":
                print("Exiting program. Restart when you're ready to try again.")
                time.sleep(1)
                return False
            else:
                print("Continuing in web-only mode...")
                self.web_only_mode = True
                state_tracker.update_state('control_mode', 'web_only')
                return True
        except KeyboardInterrupt:
            # If user presses Ctrl+C, default to web-only mode
            print("\nContinuing in web-only mode...")
            self.web_only_mode = True
            state_tracker.update_state('control_mode', 'web_only')
            return True
    
    def wait_for_controller(self, timeout=60):
        """
        Wait for a controller to be connected, with a timeout
        
        Args:
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            bool: True if a controller was found, False otherwise
        """
        # Check if we should skip the interactive wait
        if config.get("development", "skip_hardware_check"):
            log_info("Skipping controller wait due to configuration")
            return False
            
        self.display_connection_instructions()
        
        # Make timeout configurable
        timeout = config.get("controller", "connection_timeout") if config.get("controller", "connection_timeout") is not None else timeout
        
        start_time = time.time()
        check_interval = 2  # Check every 2 seconds
        
        try:
            while (time.time() - start_time) < timeout:
                if self.find_controller():
                    print("\n✓ PS4 controller connected successfully!")
                    return True
                
                # Check if Bluetooth has new devices
                try:
                    result = subprocess.run(['bluetoothctl', 'devices'], 
                                           capture_output=True, text=True, check=False)
                    ps_devices = [line for line in result.stdout.split('\n') 
                                 if 'dual' in line.lower() or 'playstation' in line.lower() 
                                 or 'wireless controller' in line.lower()]
                    
                    if ps_devices and not self.bluetooth_connected:
                        print(f"\nDetected potential PS4 controllers: {ps_devices}")
                        print("Try connecting in bluetoothctl if not already connected")
                        
                except Exception:
                    pass
                
                # Display countdown and remaining time
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                print(f"\rWaiting for controller... {int(remaining)}s remaining  ", end="")
                
                time.sleep(check_interval)
            
            print("\n\nController connection timed out.")
            return False
            
        except KeyboardInterrupt:
            print("\n\nController connection cancelled by user.")
            return False
    
    def start(self):
        """Initialize and start controller input handling"""
        log_info("Attempting to start PS4 controller...")

        # Check if already found by the initial check in main.py
        if self.device:
            log_info("Controller device already found, starting input loop.")
            return self._start_input_thread()

        # If evdev is not available, cannot proceed
        if not EVDEV_AVAILABLE:
            log_error("Evdev module is required for PS4 controller but not installed.")
            self.web_only_mode = True
            return False # Indicate failure to start controller

        # Try to find controller if not already found
        if not self.find_controller():
            log_warning("find_controller failed during start sequence.")
            # Display connection help and potentially enter web-only mode
            self.display_connection_instructions()
            if not self.prompt_web_only_mode():
                log_info("User chose to exit instead of using web-only mode.")
                return False # User chose to exit
            else:
                 log_info("Proceeding in web-only mode.")
                 # Mode will be set by web_control if used
                 return True # Indicate success (in web-only mode)

        # If controller was found by find_controller() call within start()
        log_info(f"Controller {self.device.name} found successfully during start sequence.")
        return self._start_input_thread()

    def _start_input_thread(self):
        """Starts the background thread for reading input"""
        if self.running:
            log_warning("Input thread already running.")
            return True

        if not self.device:
            log_error("Cannot start input thread, no device available.")
            self.web_only_mode = True # Fallback to web-only
            return False

        self.stop_input.clear()
        self.input_thread = threading.Thread(target=self._input_loop)
        self.input_thread.daemon = True
        self.input_thread.start()
        self.running = True
        log_info("PS4 controller input thread started.")
        control_manager.set_mode(ControlMode.PS4) # Set mode only when input starts
        return True

    def stop(self):
        """Stop PS4 controller input processing"""
        if not self.running:
            return False
            
        try:
            self.stop_input.set()
            if self.input_thread and self.input_thread.is_alive():
                self.input_thread.join(timeout=1.0)
            
            self.running = False
            log_info("PS4 controller input stopped")
            return True
        except Exception as e:
            log_error(f"Error stopping PS4 controller input: {e}")
            return False
    
    def _input_loop(self):
        """Read and process controller events using evdev's read_loop()"""
        log_info("Starting PS4 controller input loop (using read_loop).")
        if not self.device:
            log_error("Input loop started without a valid controller device.")
            self.running = False
            return

        local_device = None
        device_path = self.device.path

        try:
            log_info(f"Attempting to open device {device_path} for read_loop...")
            local_device = InputDevice(device_path)
            log_info(f"Device {device_path} opened successfully.")
            
            try:
                log_info(f"Attempting to grab exclusive access to {device_path}...")
                # local_device.grab() # <-- Comment out grab
                log_info(f"Successfully grabbed {device_path}.") # <-- Log message might be misleading now
            except OSError as grab_err:
                if 'Operation not permitted' in str(grab_err):
                    log_error(f"Permission error grabbing {device_path}. Try running script with sudo? (Continuing without grab)")
                else:
                    log_warning(f"Failed to grab exclusive access to {device_path}: {grab_err} (Continuing without grab)")
            except Exception as grab_ex:
                log_warning(f"Unexpected error during grab(): {grab_ex} (Continuing without grab)")

            event_count = 0
            log_info(f"Entering blocking read_loop for {device_path}...")
            
            # Use the read_loop generator
            for event in local_device.read_loop():
                # Check stop condition *inside* the loop
                if self.stop_input.is_set():
                    log_info("Stop signal received during read_loop, exiting loop.")
                    break 
                    
                event_count += 1
                log_debug(f"--- Event {event_count} received via read_loop --- Type: {event.type}, Code: {event.code}, Value: {event.value}")
                
                processed = False
                if event.type == ecodes.EV_KEY:
                    self._process_button_event(event)
                    processed = True
                elif event.type == ecodes.EV_ABS:
                    self._process_axis_event(event)
                    processed = True
                
                # Recalculate movement after any relevant event
                if processed:
                    self._process_movement()
                    
        except BlockingIOError:
            # This error might occur if the device buffer is temporarily empty
            # but read_loop should handle this internally usually. Log if it happens.
            log_warning("BlockingIOError caught during read_loop. This might indicate an issue.")
            # No need to sleep here, read_loop will block until next event or error
            pass # Should not happen often with read_loop, but handle just in case
        except OSError as e:
            log_error(f"Controller disconnected or read error in read_loop: {e}")
            self.device = None # Mark controller as disconnected
            # Optionally attempt reconnect here if configured
        except Exception as e:
            log_error(f"Unexpected error in input loop (read_loop): {e}", exc_info=True)
        finally:
            log_info("Exiting PS4 controller read_loop.")
            if local_device:
                try:
                    # Release grab if held
                    # Check if device is still open before ungrabbing
                    if local_device.fileno() != -1: 
                        log_debug(f"Attempting to ungrab {device_path}")
                        # local_device.ungrab() # <-- Comment out ungrab
                    else:
                        log_debug(f"Device {device_path} already closed, skipping ungrab.")
                except Exception as ungrab_err:
                    log_warning(f"Error ungrabbing device {device_path}: {ungrab_err}")
                try:
                    # Close the device
                    if local_device.fileno() != -1:
                        log_debug(f"Attempting to close device {device_path}")
                        local_device.close()
                    else:
                        log_debug(f"Device {device_path} already closed, skipping close.")
                except Exception as close_err:
                    log_warning(f"Error closing device {device_path}: {close_err}")
            self.running = False # Ensure running flag is set to False
            log_info("PS4 controller input loop finished.")

    def _process_button_event(self, event):
        """Process button press/release events"""
        button_name = self.button_map.get(event.code)
        if button_name:
            is_pressed = (event.value == 1)
            self.buttons[button_name] = is_pressed
            log_debug(f"Button event: {button_name} {'pressed' if is_pressed else 'released'}")
            
            # Trigger actions based on button press (not release)
            if is_pressed:
                 action = None
                 if button_name == 'x':
                     # Example: Stop motors
                     action = ControlAction.STOP
                     log_info("PS4: X pressed -> STOP")
                 elif button_name == 'triangle':
                     # Example: Take photo
                     action = ControlAction.TAKE_PHOTO
                     log_info("PS4: Triangle pressed -> TAKE_PHOTO")
                 elif button_name == 'circle':
                      # Example: Toggle Knight Rider
                      action = ControlAction.TOGGLE_KNIGHT_RIDER
                      log_info("PS4: Circle pressed -> TOGGLE_KNIGHT_RIDER")
                 elif button_name == 'square':
                      # Example: Toggle Party Mode
                      action = ControlAction.TOGGLE_PARTY_MODE
                      log_info("PS4: Square pressed -> TOGGLE_PARTY_MODE")
                 # Add other button actions here...
                 
                 if action:
                     # Ensure controller has priority before sending action
                     if control_manager.current_mode == ControlMode.PS4:
                          control_manager.execute_action(action, source="ps4")
                     else:
                          log_warning(f"PS4 action {action} ignored, current mode is {control_manager.current_mode}")

    def _process_axis_event(self, event):
        """Process joystick/trigger events"""
        axis_name = self.axis_map.get(event.code)
        if axis_name:
            # Normalize axis value from 0-255 (triggers) or ~-32k to +32k (sticks) to -1 to 1 or 0 to 1
            if 'trigger' in axis_name or 'l2' in axis_name or 'r2' in axis_name:
                # Triggers 0 to 255 -> 0 to 1
                value = event.value / 255.0
            elif 'dpad' in axis_name:
                 # Dpad -1, 0, 1 - Keep as is for now
                 value = event.value
            else:
                # Sticks roughly -32768 to 32767 -> -1 to 1
                value = event.value / 32767.0
                # Clamp value to ensure it's within -1 to 1 range
                value = max(-1.0, min(1.0, value))
                
            self.axes[axis_name] = value
            log_debug(f"Axis event: {axis_name} = {value:.2f} (raw: {event.value})")
    
    def _process_movement(self):
        """Process movement based on joystick positions"""
        # Tank drive mode - left stick controls left track, right stick controls right track
        left_y = -self.axes['left_y']  # Invert Y axis so positive is forward
        right_y = -self.axes['right_y']  # Invert Y axis so positive is forward
        
        # Apply deadzone and scale by max speed
        left_speed = 0 if abs(left_y) < self.deadzone else left_y * self.max_speed
        right_speed = 0 if abs(right_y) < self.deadzone else right_y * self.max_speed
        
        # Set motor speeds directly if values have changed
        if left_speed != 0 or right_speed != 0:
            control_manager.robot.set_left_speed(left_speed)
            control_manager.robot.set_right_speed(right_speed)
            
            # Update state tracker for movement direction
            if left_speed > 0 and right_speed > 0:
                movement = 'forward'
            elif left_speed < 0 and right_speed < 0:
                movement = 'backward'
            elif left_speed < right_speed:
                movement = 'right'
            elif left_speed > right_speed:
                movement = 'left'
            else:
                movement = 'stopped'
                
            state_tracker.update_state('movement', movement)
        elif left_speed == 0 and right_speed == 0 and (
                self.axes['left_y'] == 0 and self.axes['right_y'] == 0):
            # Stop motors if sticks are centered
            control_manager.robot.disable_motors()
            state_tracker.update_state('movement', 'stopped')

# Create global PS4 controller instance
ps4_controller = PS4Controller() 