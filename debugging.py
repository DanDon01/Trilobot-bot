"""
Debugging module for Trilobot

This module provides debugging utilities for the Trilobot project.
It includes logging, state tracking, and performance monitoring.
"""

import logging
import time
import os
from datetime import datetime

# Configure logging
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DIRECTORY = 'logs'

# Create logs directory if it doesn't exist
if not os.path.exists(LOG_DIRECTORY):
    os.makedirs(LOG_DIRECTORY)

# Generate log filename with timestamp
LOG_FILENAME = os.path.join(LOG_DIRECTORY, f'trilobot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

# Configure root logger
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILENAME),
        logging.StreamHandler()  # Also output to console
    ]
)

# Create module logger
logger = logging.getLogger('trilobot')

class Performance:
    """Track performance metrics for specific operations"""
    
    @staticmethod
    def timed(func):
        """Decorator to time function execution"""
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            logger.debug(f"Function {func.__name__} took {elapsed_time:.4f} seconds to execute")
            return result
        return wrapper

class StateTracker:
    """Track the state of various robot systems"""
    
    def __init__(self):
        self.states = {
            'control_mode': 'none',        # 'ps4', 'web', 'voice', 'autonomous'
            'movement': 'stopped',         # 'forward', 'backward', 'left', 'right', 'stopped'
            'led_mode': 'off',             # 'off', 'knight_rider', 'party', 'distance', 'custom'
            'camera_mode': 'normal',       # 'normal', 'night_vision', 'targeting'
            'battery_status': 'unknown',   # 'unknown', 'good', 'low', 'critical'
            'errors': []                   # List of active errors
        }
        
    def update_state(self, key, value):
        """Update a state value and log the change"""
        if key in self.states:
            old_value = self.states[key]
            self.states[key] = value
            if old_value != value:
                logger.info(f"State change: {key} changed from '{old_value}' to '{value}'")
        else:
            logger.warning(f"Attempted to update unknown state key: {key}")
    
    def get_state(self, key):
        """Get current value of a state"""
        if key in self.states:
            return self.states[key]
        else:
            logger.warning(f"Attempted to access unknown state key: {key}")
            return None
    
    def add_error(self, error):
        """Add an error to the error list"""
        self.states['errors'].append(error)
        logger.error(f"Error added: {error}")
    
    def clear_error(self, error):
        """Remove an error from the error list"""
        if error in self.states['errors']:
            self.states['errors'].remove(error)
            logger.info(f"Error cleared: {error}")

# Create global state tracker instance
state_tracker = StateTracker()

def log_info(message):
    """Log an info message"""
    logger.info(message)

def log_error(message):
    """Log an error message"""
    logger.error(message)

def log_warning(message):
    """Log a warning message"""
    logger.warning(message)

def log_debug(message):
    """Log a debug message"""
    logger.debug(message) 