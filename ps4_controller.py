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
            # Standard PlayStation button codes
            304: 'x',          # X button (cross)
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
            
            # D-pad buttons - these might be reported as buttons on some controllers
            544: 'dpad_left',  # D-pad Left 
            545: 'dpad_right', # D-pad Right
            546: 'dpad_up',    # D-pad Up
            547: 'dpad_down',  # D-pad Down
            
            # Alternative button codes sometimes reported by DualShock 4
            # (depends on connection method and controller firmware)
            288: 'x_alt',          # X button (alt)
            289: 'circle_alt',     # Circle button (alt)
            290: 'triangle_alt',   # Triangle button (alt)
            291: 'square_alt',     # Square button (alt)
            292: 'l1_alt',         # L1 button (alt)
            293: 'r1_alt',         # R1 button (alt)
            294: 'l2_button_alt',  # L2 button (alt)
            295: 'r2_button_alt',  # R2 button (alt)
            296: 'share_alt',      # Share button (alt)
            297: 'options_alt',    # Options button (alt)
            298: 'ps_alt',         # PS button (alt)
            299: 'l3_alt',         # L3 button (alt)
            300: 'r3_alt',         # R3 button (alt)
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
        """Input event loop for a PS4 controller device."""
        from debugging import log_debug, log_info, log_error, log_warning

        # Log the start of the loop
        log_info(f"PS4Controller: Starting input loop for device: {self.device_path}")
        
        if not self.device_path:
            log_error("Cannot start input loop - no device path provided")
            return
        
        local_device = None
        
        try:
            # Open the device (without 'with' as it doesn't support context manager)
            local_device = InputDevice(self.device_path)
            log_info(f"PS4Controller: Opened device: {self.device_path}")
            
            # Set non-blocking mode
            local_device.grab()  # Grab the device exclusively
            log_info("PS4Controller: Grabbed device exclusively")
            
            # Log device capabilities
            log_info(f"PS4Controller: Device capabilities: {local_device.capabilities(verbose=True)}")
            
            # Main event loop
            event_count = 0
            last_log_time = time.time()
            
            while not self.stop_input.is_set():
                if local_device.fd < 0:
                    log_warning("PS4Controller: Device file descriptor is invalid")
                    break
                
                # Check for events (non-blocking)
                try:
                    event = local_device.read_one()
                    if event:
                        event_count += 1
                        if event.type == ecodes.EV_KEY:
                            log_info(f"PS4Controller: Button event: code={event.code}, value={event.value}")
                        elif event.type == ecodes.EV_ABS:
                            log_debug(f"PS4Controller: Axis event: code={event.code}, value={event.value}")
                        elif event.type == ecodes.EV_SYN:
                            log_debug(f"PS4Controller: Sync event received")
                        else:
                            log_debug(f"PS4Controller: Other event type: {event.type}")
                        
                        self._handle_event(event)
                    else:
                        # No events available, sleep a bit to avoid busy-waiting
                        time.sleep(0.001)  # 1 ms sleep
                except BlockingIOError:
                    # No events available, sleep a bit
                    time.sleep(0.001)  # 1 ms sleep
                except OSError as e:
                    log_error(f"PS4Controller: OS Error reading device: {e}")
                    break
                
                # Periodically log event count
                current_time = time.time()
                if current_time - last_log_time >= 5.0:  # Log every 5 seconds
                    log_info(f"PS4Controller: Processed {event_count} events in the last 5 seconds")
                    event_count = 0
                    last_log_time = current_time
                
            log_info("PS4Controller: Input loop exiting normally")
            
        except Exception as e:
            log_error(f"PS4Controller: Error in input loop: {e}")
            
        finally:
            # Ensure the device is closed properly
            if local_device is not None and local_device.fd >= 0:
                try:
                    local_device.ungrab()
                    local_device.close()
                    log_info("PS4Controller: Device closed successfully")
                except Exception as e:
                    log_error(f"PS4Controller: Error closing device: {e}")
    
    def _handle_event(self, event):
        """Handle a single event from the PS4 controller"""
        log_debug(f"PS4Controller: Handling event: type={event.type}, code={event.code}, value={event.value}")
        
        if event.type == ecodes.EV_KEY:
            self._process_button_event(event)
        elif event.type == ecodes.EV_ABS:
            self._process_axis_event(event)
        elif event.type == ecodes.EV_SYN:
            log_debug(f"PS4Controller: Sync event received")
            # Process movement on sync events if axes have changed
            if self.axes_changed_since_last_sync:
                log_debug("PS4Controller: Processing movement after sync event")
                self._process_movement()
                self.axes_changed_since_last_sync = False
        else:
            log_debug(f"PS4Controller: Other event type: {event.type}")

    def _process_button_event(self, event):
        """Process button press/release events (evdev)"""
        log_debug(f"--- ENTERED _process_button_event --- Code: {event.code}")
        
        # Ensure we're in PS4 control mode when buttons are used
        if control_manager.current_mode != ControlMode.PS4:
            log_info("PS4 button pressed - switching to PS4 control mode")
            control_manager.set_mode(ControlMode.PS4)
        
        # Check if button code exists in our map
        button_name = self.button_map.get(event.code)
        if button_name:
            is_pressed = (event.value == 1) # 1 for press, 0 for release, 2 for repeat (treat repeat as press)
            self.buttons[button_name] = is_pressed
            log_debug(f"EVDEV Button event: {button_name} {'pressed' if is_pressed else 'released'} (val: {event.value})")
            log_info(f"PS4 BUTTON: Code={event.code}, Name={button_name} {'PRESSED' if is_pressed else 'RELEASED'}")  # MORE VISIBLE LOG

            # Normalize alt button names to standard names
            standard_name = button_name
            if button_name.endswith('_alt'):
                standard_name = button_name[:-4]  # Remove '_alt' suffix
                log_debug(f"Normalized alt button {button_name} to {standard_name}")

            # Trigger actions based on button press (not release)
            if is_pressed: # Only trigger on initial press (value 1) or repeat (value 2)
                 action = None
                 
                 # Map standard and alt buttons to the same actions - MATCH WEB INTERFACE
                 if standard_name == 'x': 
                     action = ControlAction.TAKE_PHOTO
                     log_info("X button - TAKING PHOTO")
                 elif standard_name == 'triangle': 
                     # Toggle button LEDs, same as web interface
                     self._handle_toggle_button_leds()
                     log_info("Triangle button - TOGGLING BUTTON LEDS")
                     return  # Special handling, early return
                 elif standard_name == 'circle': 
                     action = ControlAction.TOGGLE_KNIGHT_RIDER
                     log_info("Circle button - TOGGLING KNIGHT RIDER")
                 elif standard_name == 'square': 
                     action = ControlAction.TOGGLE_PARTY_MODE
                     log_info("Square button - TOGGLING PARTY MODE")
                 # Enhanced D-pad controls
                 elif standard_name == 'dpad_up': 
                     action = ControlAction.MOVE_FORWARD
                     log_info("D-pad UP - MOVING FORWARD")
                 elif standard_name == 'dpad_down': 
                     action = ControlAction.MOVE_BACKWARD
                     log_info("D-pad DOWN - MOVING BACKWARD")
                 elif standard_name == 'dpad_left': 
                     action = ControlAction.TURN_LEFT
                     log_info("D-pad LEFT - TURNING LEFT")
                 elif standard_name == 'dpad_right': 
                     action = ControlAction.TURN_RIGHT
                     log_info("D-pad RIGHT - TURNING RIGHT")
                 elif standard_name == 'options':
                     log_info("Options button - NO ACTION ASSIGNED")
                 elif standard_name == 'share':
                     log_info("Share button - NO ACTION ASSIGNED")
                 elif standard_name == 'ps':
                     log_info("PS button - NO ACTION ASSIGNED")
                 elif standard_name in ['l1', 'r1', 'l2_button', 'r2_button', 'l3', 'r3']:
                     log_info(f"{standard_name} button - NO ACTION ASSIGNED")

                 if action:
                     # Ensure controller has priority before sending action
                     if control_manager.current_mode == ControlMode.PS4:
                          log_info(f"PS4 Event: {standard_name} pressed -> {action.name}")
                          # Add detailed debugging to see if we're getting here
                          log_info(f"BUTTON ACTION: About to call control_manager.execute_action({action}, source='ps4')")
                          # Force direct control actions for specific buttons to ensure they work
                          if action == ControlAction.STOP:
                              log_info("DIRECTLY calling robot.disable_motors()")
                              try:
                                  control_manager.robot.disable_motors()
                                  state_tracker.update_state('movement', 'stopped')
                              except Exception as e:
                                  log_error(f"Error stopping motors: {e}")
                          elif action == ControlAction.TOGGLE_KNIGHT_RIDER:
                              log_info("DIRECTLY toggling knight rider")
                              try:
                                  control_manager.knight_rider_active = not control_manager.knight_rider_active
                                  control_manager.party_mode_active = False
                                  state_tracker.update_state('led_mode', 'knight_rider' if control_manager.knight_rider_active else 'off')
                              except Exception as e:
                                  log_error(f"Error toggling knight rider: {e}")
                          elif action == ControlAction.TOGGLE_PARTY_MODE:
                              log_info("DIRECTLY toggling party mode")
                              try:
                                  control_manager.party_mode_active = not control_manager.party_mode_active
                                  control_manager.knight_rider_active = False
                                  state_tracker.update_state('led_mode', 'party' if control_manager.party_mode_active else 'off')
                              except Exception as e:
                                  log_error(f"Error toggling party mode: {e}")
                          elif action == ControlAction.TAKE_PHOTO:
                              log_info("DIRECTLY taking photo")
                              try:
                                  # Use the same code as in control_manager._handle_take_photo
                                  from camera_processor import camera_processor
                                  filepath = camera_processor.take_photo()
                                  if filepath:
                                      log_info(f"Photo captured: {filepath}")
                                  else:
                                      log_warning("Failed to capture photo (camera processor reported failure)")
                                  state_tracker.update_state('camera_mode', 'photo_taken')
                              except Exception as e:
                                  log_error(f"Error taking photo: {e}")
                          
                          # Still try the regular action execution
                          success = control_manager.execute_action(action, source="ps4")
                          log_info(f"Control action result: {'SUCCESS' if success else 'FAILED'}")
                     else:
                          log_warning(f"Button press ignored: Control mode is {control_manager.current_mode}, not PS4")
        else:
            # Log unknown button codes to help diagnose mapping issues
            log_warning(f"Unknown button code: {event.code} with value: {event.value}")
            
    def _handle_toggle_button_leds(self):
        """Toggle button LEDs - matches web interface Triangle button function"""
        log_info("PS4 controller toggling button LEDs")
        try:
            # Toggle button LEDs state
            control_manager.button_leds_active = not control_manager.button_leds_active
            
            # Set button LEDs if hardware is available
            if hasattr(control_manager, 'robot') and control_manager.robot is not None:
                try:
                    from trilobot import NUM_BUTTONS
                    for led in range(NUM_BUTTONS):
                        control_manager.robot.set_button_led(led, control_manager.button_leds_active)
                    log_info(f"Button LEDs set to {'ON' if control_manager.button_leds_active else 'OFF'}")
                except Exception as e:
                    log_error(f"Error setting button LEDs: {e}")
            else:
                log_warning("Cannot set button LEDs: Hardware not available")
        except Exception as e:
            log_error(f"Error in _handle_toggle_button_leds: {e}")

    def _process_axis_event(self, event):
        """Process joystick and trigger axis events (evdev)"""
        log_debug(f"--- ENTERED _process_axis_event --- Code: {event.code}")
        
        # Check if axis code exists in our map
        axis_name = self.axis_map.get(event.code)
        if axis_name:
            # Convert raw values to normalized -1.0 to 1.0 range
            # PS4 controller: values are typically 0-255 (center 127/128) 
            # For this controller, values range from 0-255
            raw_value = event.value
            
            # Different normalization based on axis type
            if axis_name in ['left_x', 'right_x']:
                # X-axis normalization (0=left, 255=right, 128=center)
                normalized_value = (raw_value - 128) / 128.0
            elif axis_name in ['left_y', 'right_y']:
                # Y-axis normalization (0=up, 255=down, 128=center)
                normalized_value = (raw_value - 128) / 128.0
            elif axis_name in ['l2', 'r2']:
                # Trigger normalization (0=release, 255=fully pressed)
                normalized_value = raw_value / 255.0
            else: 
                # Default normalization for other axes
                normalized_value = (raw_value - 128) / 128.0
                
            # Apply deadzone and tracking
            old_value = self.axes.get(axis_name, 0)
            delta = abs(normalized_value - old_value)
            significant_change = delta > 0.01 # Only report changes above this threshold
            
            # Log raw value for debugging
            log_debug(f"Current val: {old_value:.4f}, Delta: {delta:.4f}, Changed: {significant_change}")
            
            # Update stored value if changed significantly
            if significant_change:
                # Round to 4 decimal places to avoid micro-fluctuations
                self.axes[axis_name] = round(normalized_value, 4)
                log_debug(f"Axis {axis_name} value updated to {self.axes[axis_name]}")
                
                # Log at higher level for visibility during testing
                log_info(f"PS4 STICK: {axis_name} = {self.axes[axis_name]:.2f}")
                
                # Set flag that we've processed an axis event and need to update movement on the next SYN
                self.axes_changed_since_last_sync = True
        else:
            # Log unknown axis codes to help diagnose mapping issues
            log_warning(f"Unknown axis code: {event.code} with value: {event.value}")

    def _simulate_button_event(self, button_name, is_pressed):
        """Simulate a button event from D-pad or other sources"""
        # Only trigger events when the state changes
        current_state = self.buttons.get(button_name, False)
        if current_state != is_pressed:
            self.buttons[button_name] = is_pressed
            log_debug(f"Simulated button event: {button_name} {'pressed' if is_pressed else 'released'}")
            
            # Process the simulated button only on press
            if is_pressed:
                log_info(f"PS4 D-PAD: {button_name} PRESSED")
                # Map D-pad directions to actions
                action = None
                if button_name == 'dpad_up': action = ControlAction.MOVE_FORWARD
                elif button_name == 'dpad_down': action = ControlAction.MOVE_BACKWARD
                elif button_name == 'dpad_left': action = ControlAction.TURN_LEFT
                elif button_name == 'dpad_right': action = ControlAction.TURN_RIGHT
                
                if action and control_manager.current_mode == ControlMode.PS4:
                    control_manager.execute_action(action, source="ps4")

    def _process_movement(self):
        """Process stick and trigger values into movement commands"""
        log_debug("Entered _process_movement")
        # Safety check - ensure this isn't called when controller should be inactive
        if not self.running or self.stop_input.is_set():
            log_warning("_process_movement called when controller inactive.")
            return
        
        # First, ensure we have control
        if control_manager.current_mode != ControlMode.PS4:
            # Request control - only set once to avoid log spam
            # (but this will fail if another source has explicitly taken control)
            log_info("Setting control mode to PS4")
            if control_manager.set_mode(ControlMode.PS4):
                log_info("Successfully set control mode to PS4")
            else:
                log_warning("Failed to set control mode to PS4 - another source may have locked control")
                return
        
        # Extract values, apply deadzone
        left_x = self.axes.get('left_x', 0.0)
        left_y = self.axes.get('left_y', 0.0)
        right_x = self.axes.get('right_x', 0.0)
        right_y = self.axes.get('right_y', 0.0)
        
        # Apply deadzone to stick inputs (values below deadzone are treated as 0)
        if abs(left_x) < self.deadzone: left_x = 0
        if abs(left_y) < self.deadzone: left_y = 0
        if abs(right_x) < self.deadzone: right_x = 0
        if abs(right_y) < self.deadzone: right_y = 0
        
        # Calculate movement: the left stick Y controls forward/backward
        # Left stick X adds turning (differential steering)
        forward_speed = -left_y  # Negative because up is negative in the raw values
        turning_speed = left_x * 0.7  # Scale down turning a bit for better control
        
        # Calculate wheel speeds using differential drive model
        # Forward + turning; negative turning rotates around left wheel
        final_left_speed = forward_speed - turning_speed  # Subtracting turning for left wheel
        final_right_speed = forward_speed + turning_speed  # Adding turning for right wheel
        
        # Clamp to max speed
        final_left_speed = max(-self.max_speed, min(self.max_speed, final_left_speed))
        final_right_speed = max(-self.max_speed, min(self.max_speed, final_right_speed))
        
        log_debug(f"Final wheel speeds: L={final_left_speed:.4f}, R={final_right_speed:.4f}")

        # Set motor speeds through control manager
        if control_manager.current_mode == ControlMode.PS4:
            # Only log and move if there's actual movement
            if abs(final_left_speed) > 0.01 or abs(final_right_speed) > 0.01:
                log_info(f"PS4 MOVEMENT: L={final_left_speed:.2f}, R={final_right_speed:.2f}")
            else:
                log_debug("PS4 sticks centered (no movement)")
            
            # Always call set_motor_speeds - it handles the stopped case too
            control_manager.set_motor_speeds(final_left_speed, final_right_speed)
        else:
            log_warning(f"PS4 movement ignored, current mode is {control_manager.current_mode}")


# Create global PS4 controller instance
ps4_controller = PS4Controller()
# Add the flag needed for SYN event processing
ps4_controller.axes_changed_since_last_sync = False 