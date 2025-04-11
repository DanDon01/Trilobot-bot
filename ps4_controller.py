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
from debugging import log_info, log_error, log_warning, state_tracker
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
                    devices_found.append(f"{device.name} at {device_path}")
                    
                    # Look for PS4 controller keywords in the device name
                    if ("sony" in device.name.lower() or 
                        "playstation" in device.name.lower() or 
                        "wireless controller" in device.name.lower() or
                        "dualshock" in device.name.lower()):
                        self.device = device
                        log_info(f"Found PS4 controller: {device.name} at {device_path}")
                        return True
                except Exception as e:
                    log_warning(f"Error checking device: {e}")
                    continue
            
            # If no devices found, log the available devices
            if devices_found:
                log_warning(f"No PS4 controller found. Available devices: {devices_found}")
            else:
                log_warning("No input devices found")
                
            return False
        except Exception as e:
            log_error(f"Error finding PS4 controller: {e}")
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
        print("2. On the Raspberry Pi, run these commands in a separate terminal if needed:")
        print("   $ bluetoothctl")
        print("   [bluetooth]# agent on")
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
        self.display_connection_instructions()
        
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
        """Start PS4 controller input processing"""
        if self.running:
            log_warning("PS4 controller already running")
            return False
            
        if not EVDEV_AVAILABLE:
            log_error("Evdev module not available. Cannot start PS4 controller.")
            # Continue in web-only mode
            return self.prompt_web_only_mode()
            
        # Find controller if not already connected
        if not self.device:
            # First try to find an already connected controller
            if not self.find_controller():
                # If not found, attempt to establish Bluetooth connection
                log_info("No PS4 controller found. Attempting Bluetooth connection...")
                
                # Try a quick connection first
                for _ in range(2):
                    if self.attempt_bluetooth_connection():
                        break
                    time.sleep(1)
                
                # If still not connected, wait for user to connect
                if not self.device:
                    if self.wait_for_controller():
                        log_info("PS4 controller connected via Bluetooth")
                        self.bluetooth_connected = True
                    else:
                        # No controller after waiting, prompt about web-only mode
                        return self.prompt_web_only_mode()
        
        try:
            # Start input thread
            self.stop_input.clear()
            self.input_thread = threading.Thread(target=self._input_loop)
            self.input_thread.daemon = True
            self.input_thread.start()
            
            self.running = True
            log_info("PS4 controller input started")
            return True
        except Exception as e:
            log_error(f"Error starting PS4 controller input: {e}")
            # Continue in web-only mode
            return self.prompt_web_only_mode()
    
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
        """Main loop for processing controller input"""
        log_info("PS4 controller input loop started")
        
        try:
            # Set PS4 mode
            control_manager.set_mode(ControlMode.PS4)
            
            # Process events
            for event in self.device.read_loop():
                if self.stop_input.is_set():
                    break
                    
                # Process different event types
                if event.type == ecodes.EV_KEY:  # Button event
                    self._process_button_event(event)
                elif event.type == ecodes.EV_ABS:  # Joystick/trigger event
                    self._process_axis_event(event)
                
                # Process combined inputs to derive movement
                self._process_movement()
        except Exception as e:
            log_error(f"Error in PS4 controller input loop: {e}")
            # Try to reconnect if the controller disconnected
            time.sleep(2)
            if not self.stop_input.is_set():
                log_info("Attempting to reconnect to PS4 controller...")
                self.device = None
                self.bluetooth_connected = False
                
                # Make a reconnection attempt
                if self.attempt_bluetooth_connection():
                    log_info("PS4 controller reconnected, restarting input loop")
                    self._input_loop()
                else:
                    log_warning("Failed to reconnect to PS4 controller")
                    # Automatically switch to web-only mode
                    self.web_only_mode = True
                    control_manager.set_mode(ControlMode.WEB)
                    state_tracker.update_state('control_mode', 'web_only')
    
    def _process_button_event(self, event):
        """Process button press/release events"""
        if event.code in self.button_map:
            button_name = self.button_map[event.code]
            pressed = (event.value == 1)
            
            # Update button state
            self.buttons[button_name] = pressed
            
            if pressed:
                log_info(f"Button pressed: {button_name}")
                
                # Handle specific button actions
                if button_name == 'x':  # X button
                    control_manager.execute_action(ControlAction.STOP)
                elif button_name == 'triangle':  # Triangle button
                    # Toggle button LEDs
                    control_manager.button_leds_active = not control_manager.button_leds_active
                elif button_name == 'circle':  # Circle button
                    control_manager.execute_action(ControlAction.TOGGLE_KNIGHT_RIDER)
                elif button_name == 'square':  # Square button
                    control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE)
                elif button_name == 'share':  # Share button
                    control_manager.execute_action(ControlAction.TAKE_PHOTO)
                elif button_name == 'ps':  # PS button
                    control_manager.execute_action(ControlAction.EMERGENCY_STOP)
    
    def _process_axis_event(self, event):
        """Process joystick and trigger events"""
        if event.code in self.axis_map:
            axis_name = self.axis_map[event.code]
            
            # Normalize axis values to -1 to 1 range
            if axis_name in ['left_x', 'left_y', 'right_x', 'right_y']:
                # Joystick values typically range from -32768 to 32767
                value = event.value / 32767.0
                if abs(value) < self.deadzone:
                    value = 0.0
            elif axis_name in ['l2', 'r2']:
                # Trigger values typically range from 0 to 255
                value = event.value / 255.0
            else:
                # D-pad values are -1, 0, or 1
                value = event.value
            
            # Update axis state
            self.axes[axis_name] = value
    
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