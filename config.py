"""
Configuration module for Trilobot

This module provides centralized configuration management for the Trilobot project.
It includes hardware settings, performance tuning, and feature toggles.
"""

import os
import json
import logging

logger = logging.getLogger('trilobot.config')

# Default configuration
DEFAULT_CONFIG = {
    # Movement settings
    "movement": {
        "max_speed": 0.8,           # Maximum motor speed (0.0-1.0)
        "stick_deadzone": 0.15,      # Controller deadzone (0.0-1.0)
        "acceleration": 0.5,         # Acceleration factor
        "turn_distance": 30,         # Distance in cm before turning
    },
    
    # LED settings
    "leds": {
        "knight_rider_interval": 0.1,   # Seconds between knight rider updates
        "party_mode_interval": 0.2,     # Seconds between party mode updates
        "button_debounce_time": 0.3,    # Button debounce time in seconds
        "distance_bands": [20, 80, 100], # Distance thresholds for LED colors
    },
    
    # Camera settings
    "camera": {
        "resolution": [640, 480],     # Camera resolution [width, height]
        "framerate": 20,              # Camera framerate
        "stream_port": 8000,          # Stream server port
        "quality": 8,                 # JPEG quality (1-10)
    },
    
    # Controller settings
    "controller": {
        "connection_timeout": 20,     # Seconds to wait for PS4 controller connection
        "auto_reconnect": True,       # Attempt to reconnect if controller disconnects
        "reconnect_attempts": 3,      # Number of reconnection attempts
    },
    
    # Web server settings
    "web_server": {
        "port": 5000,                 # Web server port
        "host": "0.0.0.0",            # Web server host
        "debug": False,               # Flask debug mode
    },
    
    # Voice settings
    "voice": {
        "enabled": False,             # Voice control enabled
        "cache_dir": "responses",     # Directory for cached responses
        "volume": 80,                 # Volume percentage
        "activation_phrase": "hey trilobot",  # Wake word
        "elevenlabs_api_key": "",     # ElevenLabs API key (empty = disabled)
        "elevenlabs_voice_id": "Josh", # ElevenLabs voice ID to use
        "elevenlabs_voices": {        # Available ElevenLabs voice options
            "Josh": "TxGEqnHWrfWFTfGW9XjX",
            "Rachel": "21m00Tcm4TlvDq8ikWAM",
            "Domi": "AZnzlk1XvdvUeBnXmlld",
            "Bella": "EXAVITQu4vr4xnSDxMaL",
            "Antoni": "ErXwobaYiN019PkySvjV",
            "Thomas": "GBv7mTt0atIp3Br8iCZE",
            "Elli": "MF3mGyEYCl7XYWbV9V6O"
        },
    },
    
    # Vision settings
    "vision": {
        "enabled": False,             # Computer vision disabled (OpenCV removed)
        "info": "Computer vision features have been removed due to OpenCV dependencies being problematic on this system",
    },
    
    # Debugging settings
    "debug": {
        "log_level": "INFO",         # Logging level
        "performance_tracking": True, # Track performance metrics
        "state_tracking": True,       # Track state changes
    },
    
    # Development settings
    "development": {
        "skip_hardware_check": False, # Skip hardware check for testing
        "disable_camera": False,      # Disable camera for testing
    }
}

class Config:
    """Configuration manager for Trilobot"""
    
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self):
        """Load configuration from file or create default"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                    logger.info(f"Configuration loaded from {self.config_path}")
                    
                    # Merge with defaults for any missing values
                    merged_config = DEFAULT_CONFIG.copy()
                    self._deep_update(merged_config, loaded_config)
                    return merged_config
            else:
                # No config file, create one with defaults
                self._save_config(DEFAULT_CONFIG)
                logger.info(f"Default configuration created at {self.config_path}")
                return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            logger.warning("Using default configuration")
            return DEFAULT_CONFIG
    
    def _deep_update(self, target, source):
        """Recursively update nested dictionaries"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    def _save_config(self, config=None):
        """Save configuration to file"""
        if config is None:
            config = self.config
            
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
            logger.info(f"Configuration saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
    
    def get(self, section, key=None):
        """Get a configuration value"""
        try:
            if key is None:
                return self.config[section]
            return self.config[section][key]
        except KeyError:
            logger.warning(f"Configuration key not found: {section}/{key}")
            return None
    
    def set(self, section, key, value):
        """Set a configuration value"""
        try:
            if section not in self.config:
                self.config[section] = {}
            
            self.config[section][key] = value
            self._save_config()
            logger.info(f"Configuration updated: {section}/{key} = {value}")
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
    
    def reload(self):
        """Reload configuration from file"""
        self.config = self._load_config()
        logger.info("Configuration reloaded")

# Create global config instance
config = Config() 