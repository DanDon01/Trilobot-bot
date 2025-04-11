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
from debugging import log_info, log_error, log_warning, state_tracker, log_debug
from config import config

logger = logging.getLogger('trilobot.control')

# --- Trilobot Hardware Initialization ---
# This section attempts to import the necessary library and initialize the hardware.
# It is designed to run on the Raspberry Pi with Trilobot hardware attached.

tbot = None

try:
    # Attempt to import the main Trilobot class
    from trilobot import Trilobot
    log_info("Successfully imported Trilobot library.")

    # Attempt to import necessary constants
    try:
        from trilobot import (
            NUM_UNDERLIGHTS, NUM_BUTTONS,
            LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT,
            LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT,
            LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
        )
        log_info("Successfully imported constants from Trilobot library.")
    except ImportError:
        # Define defaults if constants cannot be imported (should not happen with standard install)
        log_warning("Could not import constants from Trilobot library. Using default values.")
        NUM_UNDERLIGHTS = 6
        NUM_BUTTONS = 6
        LIGHT_FRONT_LEFT = 0
        LIGHT_FRONT_RIGHT = 1
        LIGHT_MIDDLE_LEFT = 2
        LIGHT_MIDDLE_RIGHT = 3
        LIGHT_REAR_LEFT = 4
        LIGHT_REAR_RIGHT = 5

    # Attempt to initialize the Trilobot hardware
    log_info("Initializing Trilobot hardware...")
    tbot = Trilobot()
    log_info("Trilobot hardware initialized successfully.")

except ImportError as e:
    log_error(f"********************************************************")
    log_error(f"* CRITICAL ERROR: Failed to import Trilobot library!   *")
    log_error(f"* Error Details: {e}                            *")
    log_error(f"*                                                      *")
    log_error(f"* This program requires the Trilobot library to run.   *")
    log_error(f"* Please ensure it's installed on your Raspberry Pi:   *")
    log_error(f"*   sudo pip3 install trilobot                         *")
    log_error(f"* Or run the Pimoroni installer:                       *")
    log_error(f"*   curl -sSL https://get.pimoroni.com/trilobot | bash *")
    log_error(f"********************************************************")
    sys.exit(1) # Exit immediately if library is not found

except Exception as e:
    log_error(f"***********************************************************")
    log_error(f"* CRITICAL ERROR: Failed to initialize Trilobot hardware! *")
    log_error(f"* Error Details: {e}                             *")
    log_error(f"*                                                         *")
    log_error(f"* Please check the following on your Raspberry Pi:        *")
    log_error(f"* 1. Is the Trilobot board securely connected?            *")
    log_error(f"* 2. Is the Raspberry Pi power supply sufficient?         *")
    log_error(f"* 3. Does the user '{os.getlogin() if hasattr(os, 'getlogin') else 'current'}' have permissions? *")
    log_error(f"*    (Try adding user to gpio, i2c, spi groups)         *")
    log_error(f"*    sudo usermod -a -G gpio,i2c,spi $USER              *")
    log_error(f"*    (You may need to log out and back in after)        *")
    log_error(f"***********************************************************")
    sys.exit(1) # Exit immediately if hardware initialization fails
# --- End Trilobot Hardware Initialization ---

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
        # Ensure we received a valid robot object (should be the initialized tbot)
        if robot is None:
             log_error("ControlManager initialized without a valid robot object!")
             # This condition should technically not be reached due to sys.exit above
             # but adding as a safeguard.
             sys.exit(1)
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
        # Ensure motors are stopped
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

        log_info(f"Executing action: {action} with value: {value} from source: {source}")

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
        self.robot.disable_motors()
        self.robot.clear_underlighting()
        state_tracker.update_state('movement', 'emergency_stopped')
        log_warning("Emergency stop activated")

    def _handle_toggle_light(self, light_index):
        """Handle toggle light action"""
        # Example: Toggle a specific underlight
        # This requires knowing the current state, which isn't tracked here yet.
        # For demonstration, just turn it blue.
        if light_index is not None and light_index < NUM_UNDERLIGHTS:
            self.robot.set_underlight(light_index, 0, 0, 255)
            log_info(f"Set underlight {light_index} to blue (toggle logic not implemented)")
        else:
            log_warning(f"Invalid light index for toggle: {light_index}")

    def _handle_toggle_knight_rider(self):
        """Handle toggle knight rider effect"""
        self.knight_rider_active = not self.knight_rider_active
        self.party_mode_active = False # Turn off party mode if activating knight rider

        state_tracker.update_state('led_mode', 'knight_rider' if self.knight_rider_active else 'off')
        log_info(f"Knight Rider effect: {'ON' if self.knight_rider_active else 'OFF'}")
        # Actual LED effect needs to be implemented in a separate loop or process

    def _handle_toggle_party_mode(self):
        """Handle toggle party mode effect"""
        self.party_mode_active = not self.party_mode_active
        self.knight_rider_active = False # Turn off knight rider if activating party mode

        state_tracker.update_state('led_mode', 'party' if self.party_mode_active else 'off')
        log_info(f"Party mode: {'ON' if self.party_mode_active else 'OFF'}")
        # Actual LED effect needs to be implemented in a separate loop or process

    def _handle_take_photo(self):
        """Handle take photo action"""
        # Interface with the camera processor to take a photo
        from camera_processor import camera_processor

        try:
            filepath = camera_processor.take_photo()
            if filepath:
                log_info(f"Photo captured: {filepath}")
            else:
                log_warning("Failed to capture photo (camera processor reported failure)")

        except Exception as e:
            log_error(f"Error interfacing with camera_processor to take photo: {e}")

        state_tracker.update_state('camera_mode', 'photo_taken')

# Create global control manager instance, passing the initialized tbot object
# This line will only be reached if tbot was successfully initialized above
control_manager = ControlManager(tbot) 