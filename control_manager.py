"""
Control Manager for Trilobot

This module provides a unified control system for the Trilobot,
handling inputs from various sources (PS4 controller, web interface,
voice commands) and coordinating them.
"""

import threading
import time
import logging
import sys
import os
from enum import Enum
from typing import Dict, Tuple, Optional, Callable

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker
from config import config

logger = logging.getLogger('trilobot.control')

# Import trilobot class
trilobot_available = False
import_error = None

# Check if we should force mock mode based on config
force_mock = config.get("development", "force_mock") if config.get("development", "force_mock") is not None else False

if force_mock:
    log_warning("Force mock mode enabled in config, using MockTrilobot")
    trilobot_available = False
else:
    # Try to import from different paths to handle various install methods
    possible_paths = [
        os.path.expanduser('~/Pimoroni/trilobot/library'),
        '/usr/local/lib/python3.11/dist-packages',
        '/usr/lib/python3/dist-packages',
    ]
    
    for path in possible_paths:
        if path not in sys.path and os.path.exists(path):
            sys.path.append(path)
            log_info(f"Added potential Trilobot path: {path}")
    
    try:
        from trilobot import Trilobot
        log_info("Successfully imported Trilobot library")
        trilobot_available = True
    except ImportError as e:
        import_error = str(e)
        log_warning(f"Failed to import Trilobot: {e}")
        log_warning("Will use MockTrilobot instead")
        trilobot_available = False
    except Exception as e:
        import_error = str(e)
        log_warning(f"Error importing Trilobot: {e}")
        log_warning("Will use MockTrilobot instead")
        trilobot_available = False

# Initialize real or mock Trilobot
if trilobot_available:
    try:
        tbot = Trilobot()
        log_info("Initialized real Trilobot hardware")
    except Exception as e:
        log_error(f"Failed to initialize Trilobot hardware: {e}")
        trilobot_available = False
        # Fall back to mock if hardware initialization fails
else:
    # Mock trilobot for development or when real hardware isn't available
    class MockTrilobot:
        def __init__(self):
            self.left_speed = 0
            self.right_speed = 0
            self.motors_enabled = False
            logger.warning("Using MockTrilobot (no hardware)")
            
            # Debug - help user install trilobot if not available
            if import_error and "No module named" in import_error:
                logger.warning("To install Trilobot, run: ")
                logger.warning("  curl -sSL https://get.pimoroni.com/trilobot | bash")
        
        def set_left_speed(self, speed):
            self.left_speed = speed
            self.motors_enabled = True
            logger.debug(f"Mock: Left motor speed set to {speed}")
        
        def set_right_speed(self, speed):
            self.right_speed = speed
            self.motors_enabled = True
            logger.debug(f"Mock: Right motor speed set to {speed}")
        
        def disable_motors(self):
            self.left_speed = 0
            self.right_speed = 0
            self.motors_enabled = False
            logger.debug("Mock: Motors disabled")
        
        def clear_underlighting(self, show=True):
            logger.debug("Mock: Cleared underlighting")
        
        def set_underlight(self, light, r_or_rgb, g=None, b=None, show=True):
            if g is None and b is None:
                # RGB tuple provided
                logger.debug(f"Mock: Set underlight {light} to {r_or_rgb}")
            else:
                # Individual r,g,b values
                logger.debug(f"Mock: Set underlight {light} to ({r_or_rgb}, {g}, {b})")
        
        def fill_underlighting(self, r_or_rgb, g=None, b=None):
            if g is None and b is None:
                # RGB tuple provided
                logger.debug(f"Mock: Fill underlighting with {r_or_rgb}")
            else:
                # Individual r,g,b values
                logger.debug(f"Mock: Fill underlighting with ({r_or_rgb}, {g}, {b})")
                
        def set_button_led(self, button, state):
            logger.debug(f"Mock: Set button LED {button} to {state}")
    
    tbot = MockTrilobot()

# Add constants if using mock and they're not available
if not trilobot_available:
    # Define constants that would normally be from trilobot
    if not 'NUM_UNDERLIGHTS' in globals():
        globals()['NUM_UNDERLIGHTS'] = 6
    if not 'NUM_BUTTONS' in globals():
        globals()['NUM_BUTTONS'] = 6
    if not 'LIGHT_FRONT_LEFT' in globals():
        globals()['LIGHT_FRONT_LEFT'] = 0
    if not 'LIGHT_FRONT_RIGHT' in globals():
        globals()['LIGHT_FRONT_RIGHT'] = 1
    if not 'LIGHT_MIDDLE_LEFT' in globals():
        globals()['LIGHT_MIDDLE_LEFT'] = 2
    if not 'LIGHT_MIDDLE_RIGHT' in globals():
        globals()['LIGHT_MIDDLE_RIGHT'] = 3
    if not 'LIGHT_REAR_LEFT' in globals():
        globals()['LIGHT_REAR_LEFT'] = 4
    if not 'LIGHT_REAR_RIGHT' in globals():
        globals()['LIGHT_REAR_RIGHT'] = 5

class ControlMode(Enum):
    """Control modes for the Trilobot"""
    NONE = 0
    PS4 = 1
    WEB = 2
    VOICE = 3
    AUTONOMOUS = 4

class ControlAction(Enum):
    """Control actions for the Trilobot"""
    MOVE_FORWARD = 1
    MOVE_BACKWARD = 2
    TURN_LEFT = 3
    TURN_RIGHT = 4
    STOP = 5
    TOGGLE_LIGHT = 6
    TOGGLE_KNIGHT_RIDER = 7
    TOGGLE_PARTY_MODE = 8
    TAKE_PHOTO = 9
    EMERGENCY_STOP = 10

class ControlManager:
    """Unified control manager for Trilobot"""
    
    def __init__(self, robot):
        self.robot = robot
        self.current_mode = ControlMode.NONE
        self.mode_lock = threading.Lock()
        self.active_actions = {}
        
        # Movement settings
        self.max_speed = config.get("movement", "max_speed")
        self.acceleration = config.get("movement", "acceleration")
        self.turn_distance = config.get("movement", "turn_distance")
        self.stick_deadzone = config.get("movement", "stick_deadzone")
        
        # Current state
        self.speeds = {"left": 0.0, "right": 0.0}
        
        # Status flags
        self.knight_rider_active = False
        self.party_mode_active = False
        self.button_leds_active = False
        
        # Register state with tracker
        state_tracker.update_state('control_mode', 'none')
        state_tracker.update_state('movement', 'stopped')
        
        # Control loops
        self._stop_event = threading.Event()
        self._control_thread = None
        
        log_info("Control Manager initialized")
    
    def start(self):
        """Start the control manager"""
        if self._control_thread is None or not self._control_thread.is_alive():
            self._stop_event.clear()
            self._control_thread = threading.Thread(target=self._control_loop)
            self._control_thread.daemon = True
            self._control_thread.start()
            log_info("Control Manager started")
    
    def stop(self):
        """Stop the control manager"""
        self._stop_event.set()
        if self._control_thread and self._control_thread.is_alive():
            self._control_thread.join(timeout=1.0)
        self.robot.disable_motors()
        log_info("Control Manager stopped")
    
    def _control_loop(self):
        """Main control loop"""
        while not self._stop_event.is_set():
            # Process active actions
            self._process_actions()
            
            # Short sleep to prevent CPU hogging
            time.sleep(0.01)
    
    def _process_actions(self):
        """Process all active actions"""
        # For now, this just updates motor speeds
        # In future, could handle more complex behavior
        pass
    
    def set_mode(self, mode: ControlMode) -> bool:
        """Set the current control mode"""
        with self.mode_lock:
            old_mode = self.current_mode
            self.current_mode = mode
            log_info(f"Control mode changed from {old_mode} to {mode}")
            state_tracker.update_state('control_mode', mode.name.lower())
            return True
    
    def execute_action(self, action: ControlAction, value=None, source=None) -> bool:
        """Execute a control action"""
        # Check if source has permission to control
        if source and not self._check_permission(source):
            log_warning(f"Permission denied for {source} to execute {action}")
            return False
        
        log_info(f"Executing action: {action} with value: {value}")
        
        try:
            # Handle different actions
            if action == ControlAction.MOVE_FORWARD:
                self._handle_move_forward(value)
            elif action == ControlAction.MOVE_BACKWARD:
                self._handle_move_backward(value)
            elif action == ControlAction.TURN_LEFT:
                self._handle_turn_left(value)
            elif action == ControlAction.TURN_RIGHT:
                self._handle_turn_right(value)
            elif action == ControlAction.STOP:
                self._handle_stop()
            elif action == ControlAction.EMERGENCY_STOP:
                self._handle_emergency_stop()
            elif action == ControlAction.TOGGLE_LIGHT:
                self._handle_toggle_light(value)
            elif action == ControlAction.TOGGLE_KNIGHT_RIDER:
                self._handle_toggle_knight_rider()
            elif action == ControlAction.TOGGLE_PARTY_MODE:
                self._handle_toggle_party_mode()
            elif action == ControlAction.TAKE_PHOTO:
                self._handle_take_photo()
            else:
                log_warning(f"Unknown action: {action}")
                return False
            
            return True
            
        except Exception as e:
            log_error(f"Error executing action {action}: {e}")
            return False
    
    def _check_permission(self, source) -> bool:
        """Check if a source has permission to control"""
        # For now, always return True
        # In future, could implement more complex permission system
        return True
    
    def _handle_move_forward(self, speed=None):
        """Handle move forward action"""
        if speed is None:
            speed = self.max_speed
        
        self.robot.set_left_speed(speed)
        self.robot.set_right_speed(speed)
        state_tracker.update_state('movement', 'forward')
    
    def _handle_move_backward(self, speed=None):
        """Handle move backward action"""
        if speed is None:
            speed = self.max_speed
        
        self.robot.set_left_speed(-speed)
        self.robot.set_right_speed(-speed)
        state_tracker.update_state('movement', 'backward')
    
    def _handle_turn_left(self, speed=None):
        """Handle turn left action"""
        if speed is None:
            speed = self.max_speed
        
        self.robot.set_left_speed(-speed)
        self.robot.set_right_speed(speed)
        state_tracker.update_state('movement', 'left')
    
    def _handle_turn_right(self, speed=None):
        """Handle turn right action"""
        if speed is None:
            speed = self.max_speed
        
        self.robot.set_left_speed(speed)
        self.robot.set_right_speed(-speed)
        state_tracker.update_state('movement', 'right')
    
    def _handle_stop(self):
        """Handle stop action"""
        self.robot.disable_motors()
        state_tracker.update_state('movement', 'stopped')
    
    def _handle_emergency_stop(self):
        """Handle emergency stop action"""
        # More abrupt stop, might include other emergency actions
        self.robot.disable_motors()
        self.robot.clear_underlighting()
        state_tracker.update_state('movement', 'emergency_stopped')
        log_warning("Emergency stop activated")
    
    def _handle_toggle_light(self, light_index):
        """Handle toggle light action"""
        # This would need to be implemented based on specific light requirements
        pass
    
    def _handle_toggle_knight_rider(self):
        """Handle toggle knight rider effect"""
        self.knight_rider_active = not self.knight_rider_active
        self.party_mode_active = False if self.knight_rider_active else self.party_mode_active
        
        state_tracker.update_state('led_mode', 'knight_rider' if self.knight_rider_active else 'off')
        log_info(f"Knight Rider effect: {'ON' if self.knight_rider_active else 'OFF'}")
    
    def _handle_toggle_party_mode(self):
        """Handle toggle party mode effect"""
        self.party_mode_active = not self.party_mode_active
        self.knight_rider_active = False if self.party_mode_active else self.knight_rider_active
        
        state_tracker.update_state('led_mode', 'party' if self.party_mode_active else 'off')
        log_info(f"Party mode: {'ON' if self.party_mode_active else 'OFF'}")
    
    def _handle_take_photo(self):
        """Handle take photo action"""
        # Interface with the camera processor to take a photo
        from camera_processor import camera_processor
        
        try:
            filepath = camera_processor.take_photo()
            if filepath:
                log_info(f"Photo captured: {filepath}")
            else:
                log_warning("Failed to capture photo")
                
        except Exception as e:
            log_error(f"Error taking photo: {e}")
            
        state_tracker.update_state('camera_mode', 'photo_taken')

# Create global control manager instance
control_manager = ControlManager(tbot) 