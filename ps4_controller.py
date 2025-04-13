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
    # Log the value of the constant
    logger.debug(f"Value of ecodes.EV_ABS: {ecodes.EV_ABS}")
except ImportError:
    EVDEV_AVAILABLE = False
    logger.warning("Evdev module not available. PS4 controller support disabled.")

class PS4Controller:
    """Handler for PS4 controller input"""
    
    def __init__(self):
        self.device_path = None
        self.running = False
        self.input_thread = None
        self.stop_input = threading.Event()
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.bluetooth_connected = False
        self.web_only_mode = False
        self.axes_changed_since_last_sync = False
        
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
        
        # --- REMOVED Mappings for 'inputs' library ---
        # self.inputs_button_map = { ... }
        # self.inputs_axis_map = { ... }
        # self.inputs_axis_scale = { ... }
        # ---------------------------------------------
        
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
        """Find the specific PS4 controller device node (not touchpad/motion)."""
        if not EVDEV_AVAILABLE:
            log_error("Evdev module not available. Cannot find PS4 controller.")
            return False
            
        target_device_name = "Wireless Controller" # Adjust if name is slightly different
        excluded_names = ["Touchpad", "Motion Sensor"]
        self.device_path = None # Reset path
        potential_devices = []

        try:
            devices = [InputDevice(path) for path in list_devices()]
            for device in devices:
                log_debug(f"Checking device: {device.name} at {device.path}")
                # Check if it's the target name and not excluded
                if target_device_name in device.name and not any(ex in device.name for ex in excluded_names):
                    self.device_path = device.path
                    log_info(f"Found target PS4 controller: {device.name} at {self.device_path}")
                    # Close the temporary device object used for checking
                    try: device.close() 
                    except: pass 
                    return True
                # Keep track of potential devices for manual selection if needed
                elif "controller" in device.name.lower() or "sony" in device.name.lower() or "dualshock" in device.name.lower():
                    potential_devices.append((device, device.path))
                 # Close the temporary device object used for checking
                try: device.close() 
                except: pass

            # If target wasn't found, handle potential devices
            log_warning(f"Could not automatically find device named exactly '{target_device_name}' (excluding {excluded_names}).")
            if potential_devices:
                 log_warning(f"Found {len(potential_devices)} potential controller-like devices.")
                 # Pass paths for manual selection
                 potential_paths = [(name, path) for dev, path in potential_devices]
                 # Need to adjust _prompt_manual_device_selection to handle (name, path) tuples
                 # For now, let's fall back to the old manual selection logic if needed, 
                 # but ideally, we find the target automatically.
                 # Simplified: If automatic fails, prompt might still show irrelevant devices.
                 return self._prompt_manual_device_selection([(InputDevice(path), path) for _, path in potential_paths]) # Re-open for prompt
            else:
                 log_warning("No input devices found resembling a controller.")
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
                self.device_path = _
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

        # Check if path was already found
        if self.device_path:
            log_info("Controller device path already set, starting input loop.")
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
        log_info(f"Controller path {self.device_path} found successfully during start sequence.")
        return self._start_input_thread()

    def _start_input_thread(self):
        # --- FORCE EVDEV LOOP --- # MODIFIED
        if not (EVDEV_AVAILABLE and self.device_path):
            log_error("Cannot start evdev input thread: Evdev not available or device path not set.")
            self.web_only_mode = True
            return False
        target_loop = self._input_loop # ALWAYS use evdev loop
        log_info("Using 'evdev' library for controller (forced).") # MODIFIED
        # --- END FORCE EVDEV LOOP --- 

        """Starts the background thread for reading input"""
        if self.running:
            log_warning("Input thread already running.")
            return True

        if not self.device_path:
            log_error("Cannot start input thread, no device path available.")
            self.web_only_mode = True # Fallback to web-only
            return False

        self.stop_input.clear()
        self.input_thread = threading.Thread(target=target_loop) # Use selected loop
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
        """Input loop using evdev with non-blocking read."""
        log_info("Starting PS4 controller input loop (using evdev non-blocking).")
        if not self.device_path:
            log_error("Input loop (evdev) started without a valid device path.")
            self.running = False
            return

        device_path = self.device_path

        local_device = None
        thread_name = threading.current_thread().name
        log_info(f"Input thread '{thread_name}' started for {device_path}.")

        try:
            log_info(f"Attempting to open device {device_path} for evdev loop...")
            # Re-open the device in the thread context
            local_device = InputDevice(device_path)
            log_info(f"Device {device_path} opened successfully for evdev.")

            event_count = 0
            log_info(f"Entering blocking evdev read_loop() for {device_path}...")

            # --- Use blocking read_loop() instead of read_one() ---
            # while not self.stop_input.is_set():
            #     event = local_device.read_one()
            #     if event is None:
            #         # No event available, sleep briefly and check stop flag
            #         time.sleep(0.01)
            #         continue
            for event in local_device.read_loop():
                # Check stop condition *inside* the loop
                if self.stop_input.is_set():
                    log_info(f"Stop signal received during read_loop ({thread_name}), exiting loop.")
                    break

                # If we reach here, an event was received
                event_count += 1
                # --- LOG ALL EVENTS --- 
                log_debug(f"--- RAW EVDEV Event {event_count} --- Type: {event.type}, Code: {event.code}, Value: {event.value}")
                log_debug(f"--- Checking event type value: {event.type} (type: {type(event.type)}) ---")
                
                # --- Re-enable processing --- # MODIFIED
                processed = False
                # --- Use integer literals for type checking --- # MODIFIED
                if event.type == 1: # Was ecodes.EV_KEY
                    log_debug(f"--- Event type matched 1 (EV_KEY) ---") # MODIFIED
                    self._process_button_event(event) 
                    processed = True
                elif event.type == 3: # Was ecodes.EV_ABS
                    log_debug(f"--- Event type matched 3 (EV_ABS) ---") # MODIFIED
                    self._process_axis_event(event)   
                    processed = True
                    # --- Try calling movement directly after axis processing --- 
                    log_debug("--- Triggering movement check after ABS event ---") 
                    self._process_movement() 
                elif event.type == 0: # Was ecodes.EV_SYN
                    log_debug(f"--- Event type matched 0 (EV_SYN) ---") # MODIFIED
                    # Sync event often follows a burst of axis events
                    log_debug(f"EVDEV Sync event received (SYN_REPORT, code {event.code}, value {event.value})")
                    # --- Temporarily disable SYN-based movement trigger ---
                    processed = False # Don't re-trigger movement below for Sync
                else:
                    log_debug(f"--- Event type UNHANDLED: {event.type} ---")
                # --- End re-enable processing ---

        except BlockingIOError:
            # This might happen if read_loop is interrupted strangely
            log_warning(f"BlockingIOError caught during read_loop ({thread_name}).")
            # time.sleep(0.05) # No sleep needed for read_loop
        except OSError as e:
            # This usually means the controller disconnected
            log_error(f"Controller disconnected or read error in evdev loop ({thread_name}): {e}")
            self.device_path = None # Clear the path
            self.running = False # Ensure loop stops externally if thread dies
            # Attempt to trigger cleanup/reconnect logic if needed
        except Exception as e:
            # Use standard logger here to include traceback info
            logger.error(f"Unexpected error in evdev input loop ({thread_name}): {e}", exc_info=True)
        finally:
            log_info(f"Exiting PS4 controller evdev loop ({thread_name}).")
            if local_device:
                try:
                    if local_device.fileno() != -1:
                        log_debug(f"Attempting to close evdev device {device_path}")
                        local_device.close()
                    else:
                        log_debug(f"Evdev device {device_path} already closed.")
                except Exception as close_err:
                    log_warning(f"Error closing evdev device {device_path}: {close_err}")
            self.running = False # Ensure state reflects loop stop
            log_info(f"PS4 controller evdev input loop finished ({thread_name}).")

    def _process_button_event(self, event):
        """Process button press/release events (evdev)"""
        log_debug(f"--- ENTERED _process_button_event --- Code: {event.code}")
        # Check if button code exists in our map
        button_name = self.button_map.get(event.code)
        if button_name:
            is_pressed = (event.value == 1) # 1 for press, 0 for release, 2 for repeat (treat repeat as press)
            self.buttons[button_name] = is_pressed
            log_debug(f"EVDEV Button event: {button_name} {'pressed' if is_pressed else 'released'} (val: {event.value})")

            # Trigger actions based on button press (not release)
            if is_pressed: # Only trigger on initial press (value 1) or repeat (value 2)
                 action = None
                 if button_name == 'x': action = ControlAction.STOP
                 elif button_name == 'triangle': action = ControlAction.TAKE_PHOTO
                 elif button_name == 'circle': action = ControlAction.TOGGLE_KNIGHT_RIDER
                 elif button_name == 'square': action = ControlAction.TOGGLE_PARTY_MODE
                 # Add other button actions here...

                 if action:
                     # Ensure controller has priority before sending action
                     if control_manager.current_mode == ControlMode.PS4:
                          log_info(f"PS4 Event: {button_name} pressed -> {action.name}")
                          control_manager.execute_action(action, source="ps4")
                     else:
                          log_warning(f"PS4 action {action.name} ignored, current mode is {control_manager.current_mode}")

    def _process_axis_event(self, event):
        """Process joystick/trigger events (evdev)"""
        log_debug(f"--- ENTERED _process_axis_event --- Code: {event.code}")
        # Check if axis code exists in our map
        axis_name = self.axis_map.get(event.code)
        if axis_name:
            # Normalize axis value from 0-255 (triggers) or ~-32k to +32k (sticks) to -1 to 1 or 0 to 1
            if 'l2' in axis_name or 'r2' in axis_name: # Check includes button and analog trigger
                # Triggers 0 to 255 -> 0 to 1
                value = event.value / 255.0
            elif 'dpad' in axis_name:
                 # Dpad -1, 0, 1 - Keep as is
                 value = float(event.value) # Ensure float
            else:
                # Sticks roughly -32768 to 32767 -> -1 to 1
                # Use 32768 for normalization to be safe
                value = event.value / 32768.0
                # Clamp value to ensure it's within -1 to 1 range
                value = max(-1.0, min(1.0, value))

            # Update only if value has changed significantly
            if abs(self.axes.get(axis_name, -99) - value) > 0.01: # Use dummy value for first check
                 self.axes[axis_name] = value
                 self.axes_changed_since_last_sync = True # Flag that movement needs recalculating
                 log_debug(f"EVDEV Axis event: {axis_name} = {value:.2f} (raw: {event.value})")
                 log_debug(f"---> Set axes_changed_since_last_sync = True")

    def _process_movement(self):
        """Process movement based on joystick positions (uses self.axes)"""
        log_debug("--- ENTERED _process_movement ---")
        # Tank drive mode - left stick controls left track, right stick controls right track
        # Get current values, default to 0 if not yet set
        left_y = -self.axes.get('left_y', 0.0)  # Invert Y axis so positive is forward
        right_y = -self.axes.get('right_y', 0.0) # Invert Y axis so positive is forward

        # Apply deadzone
        left_y_deadzoned = 0 if abs(left_y) < self.deadzone else left_y
        right_y_deadzoned = 0 if abs(right_y) < self.deadzone else right_y
        
        # Scale by max speed
        target_left_speed = left_y_deadzoned * self.max_speed
        target_right_speed = right_y_deadzoned * self.max_speed

        # --- Use target speed directly ---
        final_left_speed = target_left_speed
        final_right_speed = target_right_speed

        # --- Simplified update logic ---
        # Always update motors if control mode is PS4, let ControlManager handle state
        # log_debug(f"Calculated speeds: L={final_left_speed:.2f}, R={final_right_speed:.2f}")
        if control_manager.current_mode == ControlMode.PS4:
            if abs(final_left_speed) < 0.01 and abs(final_right_speed) < 0.01:
                # If speeds are effectively zero, disable motors
                if state_tracker.get_state('movement') != 'stopped': # Avoid redundant calls
                     log_debug("Sticks centered or near zero, disabling motors.")
                     self.robot.disable_motors()
                     state_tracker.update_state('movement', 'stopped')
            else:
                # Speeds are non-zero, set them
                log_debug(f"Updating motor speeds: L={final_left_speed:.2f}, R={final_right_speed:.2f}")
                self.robot.set_left_speed(final_left_speed)
                self.robot.set_right_speed(final_right_speed)
                
                # Determine movement state for logging/state tracking
                if final_left_speed > 0 and final_right_speed > 0: movement_state = 'forward'
                elif final_left_speed < 0 and final_right_speed < 0: movement_state = 'backward'
                elif abs(final_left_speed) < 0.1 and abs(final_right_speed) < 0.1: movement_state = 'stopped' # Catch near zero case
                elif final_left_speed < final_right_speed: movement_state = 'right' # Turning right: Left forward, Right back/slower
                elif final_left_speed > final_right_speed: movement_state = 'left'  # Turning left: Right forward, Left back/slower
                else: movement_state = 'complex_turn' # Both turning diff directions but not pure left/right
                state_tracker.update_state('movement', movement_state)
        # else:
        #      log_warning(f"Movement ignored, current mode is {control_manager.current_mode}") # Already logged upstream potentially


# Create global PS4 controller instance
ps4_controller = PS4Controller()
# Add the flag needed for SYN event processing
ps4_controller.axes_changed_since_last_sync = False 