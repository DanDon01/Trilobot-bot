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

# Import trilobot class - Ensure hardware is properly detected
try:
    # First try direct import (standard installation)
    from trilobot import Trilobot
    log_info("Successfully imported Trilobot library")
    
    # Initialize the Trilobot hardware
    tbot = Trilobot()
    log_info("Initialized real Trilobot hardware")
    
    # Import needed constants
    from trilobot import (
        NUM_UNDERLIGHTS, NUM_BUTTONS,
        LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT,
        LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT,
        LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
    )
    
except ImportError as e:
    log_error(f"Critical error: Failed to import Trilobot library: {e}")
    log_error("The Trilobot hardware must be available to run this application.")
    log_error("Please make sure the Trilobot library is installed: sudo pip3 install trilobot")
    log_error("Or run: curl -sSL https://get.pimoroni.com/trilobot | bash")
    sys.exit(1)
except Exception as e:
    log_error(f"Critical error: Failed to initialize Trilobot hardware: {e}")
    log_error("Make sure the Trilobot hardware is properly connected")
    log_error("If running as non-root user, ensure user has proper permissions")
    log_error("Try running: sudo usermod -a -G gpio,spi,i2c $USER")
    sys.exit(1)

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