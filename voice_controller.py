"""
Voice Controller Module for Trilobot

This module provides voice recognition and speech synthesis capabilities
for the Trilobot, using ElevenLabs for high-quality voice generation.
"""

import os
import time
import threading
import logging
import json
from queue import Queue
import pygame
import tempfile

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker
from config import config
from control_manager import control_manager, ControlAction

logger = logging.getLogger('trilobot.voice')

# Check if voice modules are available
SPEECH_RECOGNITION_AVAILABLE = False
ELEVENLABS_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    logger.warning("SpeechRecognition module not available. Voice recognition disabled.")

try:
    from elevenlabs import generate, save, set_api_key, voices
    from elevenlabs.api import History
    ELEVENLABS_AVAILABLE = True
except ImportError:
    logger.warning("ElevenLabs module not available. Voice synthesis disabled.")

class VoiceController:
    """Controller for voice recognition and synthesis"""
    
    def __init__(self):
        self.enabled = config.get("voice", "enabled")
        self.cache_dir = config.get("voice", "cache_dir")
        self.volume = config.get("voice", "volume") / 100.0  # Convert to 0-1 range
        self.activation_phrase = config.get("voice", "activation_phrase").lower()
        
        # Create cache directory if it doesn't exist
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            
        # Initialize pygame for audio playback
        pygame.mixer.init()
        
        # Speech recognition components
        self.recognizer = None if not SPEECH_RECOGNITION_AVAILABLE else sr.Recognizer()
        self.microphone = None
        self.recognition_thread = None
        self.stop_recognition = threading.Event()
        
        # Voice command mapping
        self.command_map = {
            "move forward": ControlAction.MOVE_FORWARD,
            "go forward": ControlAction.MOVE_FORWARD,
            "forward": ControlAction.MOVE_FORWARD,
            
            "move backward": ControlAction.MOVE_BACKWARD,
            "go backward": ControlAction.MOVE_BACKWARD,
            "back up": ControlAction.MOVE_BACKWARD,
            "reverse": ControlAction.MOVE_BACKWARD,
            
            "turn left": ControlAction.TURN_LEFT,
            "go left": ControlAction.TURN_LEFT,
            "left": ControlAction.TURN_LEFT,
            
            "turn right": ControlAction.TURN_RIGHT,
            "go right": ControlAction.TURN_RIGHT,
            "right": ControlAction.TURN_RIGHT,
            
            "stop": ControlAction.STOP,
            "halt": ControlAction.STOP,
            "freeze": ControlAction.STOP,
            
            "emergency stop": ControlAction.EMERGENCY_STOP,
            "emergency halt": ControlAction.EMERGENCY_STOP,
            
            "knight rider": ControlAction.TOGGLE_KNIGHT_RIDER,
            "party mode": ControlAction.TOGGLE_PARTY_MODE,
            "take photo": ControlAction.TAKE_PHOTO,
            "take picture": ControlAction.TAKE_PHOTO,
            "capture image": ControlAction.TAKE_PHOTO,
        }
        
        # Special commands that don't map to control actions
        self.special_commands = {
            "hello": self._handle_hello,
            "hi": self._handle_hello,
            "hey": self._handle_hello,
            "status": self._handle_status,
            "status report": self._handle_status,
            "who are you": self._handle_who_are_you,
            "what are you": self._handle_who_are_you,
            "help": self._handle_help,
        }
        
        # ElevenLabs setup if available
        if ELEVENLABS_AVAILABLE:
            api_key = os.environ.get("ELEVENLABS_API_KEY")
            if api_key:
                set_api_key(api_key)
                log_info("ElevenLabs API key configured")
            else:
                log_warning("ElevenLabs API key not found in environment variables")
        
        log_info("Voice Controller initialized")
        
    def start(self):
        """Start voice recognition"""
        if not self.enabled:
            log_warning("Voice control is disabled in configuration")
            return False
            
        if not SPEECH_RECOGNITION_AVAILABLE:
            log_error("Cannot start voice recognition: Speech recognition module not available")
            return False
        
        try:
            # Find working microphone
            for mic_index, mic_name in enumerate(sr.Microphone.list_microphone_names()):
                try:
                    self.microphone = sr.Microphone(device_index=mic_index)
                    with self.microphone as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    log_info(f"Using microphone: {mic_name}")
                    break
                except Exception as e:
                    continue
            
            if not self.microphone:
                log_error("No working microphone found")
                return False
            
            # Start recognition thread
            self.stop_recognition.clear()
            self.recognition_thread = threading.Thread(target=self._recognition_loop)
            self.recognition_thread.daemon = True
            self.recognition_thread.start()
            
            log_info("Voice recognition started")
            self.speak("Voice control activated", "startup")
            return True
        except Exception as e:
            log_error(f"Error starting voice recognition: {e}")
            return False
    
    def stop(self):
        """Stop voice recognition"""
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.stop_recognition.set()
            self.recognition_thread.join(timeout=1.0)
            log_info("Voice recognition stopped")
            return True
        return False
    
    def speak(self, text, cache_name=None):
        """Generate and play text-to-speech audio"""
        if not self.enabled:
            return False
            
        # Generate cache name from text if not provided
        if cache_name is None:
            # Make a simplified version of the text for the filename
            cache_name = "".join(c for c in text if c.isalnum() or c.isspace()).lower()
            cache_name = cache_name.replace(" ", "_")[:50]  # Limit length
        
        cache_path = os.path.join(self.cache_dir, f"{cache_name}.mp3")
        
        try:
            # Check if cached version exists
            if os.path.exists(cache_path):
                log_info(f"Using cached audio for: {text}")
                self._play_audio(cache_path)
                return True
            
            # Generate new audio if ElevenLabs is available
            if ELEVENLABS_AVAILABLE:
                log_info(f"Generating speech via ElevenLabs: {text}")
                
                # Generate audio
                audio = generate(
                    text=text,
                    voice="Josh",  # Default voice
                    model="eleven_monolingual_v1"
                )
                
                # Save to cache
                save(audio, cache_path)
                
                # Play audio
                self._play_audio(cache_path)
                return True
            else:
                log_warning("ElevenLabs not available. Unable to generate speech.")
                return False
                
        except Exception as e:
            log_error(f"Error generating speech: {e}")
            return False
    
    def _play_audio(self, file_path):
        """Play an audio file"""
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        except Exception as e:
            log_error(f"Error playing audio: {e}")
    
    def _recognition_loop(self):
        """Main loop for voice recognition"""
        log_info("Voice recognition loop started")
        
        with self.microphone as source:
            # Initial adjustment for ambient noise
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            
            while not self.stop_recognition.is_set():
                try:
                    log_info("Listening for commands...")
                    
                    # Listen for audio
                    audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=5)
                    
                    # Recognize speech using Google Speech Recognition
                    try:
                        text = self.recognizer.recognize_google(audio).lower()
                        log_info(f"Recognized: {text}")
                        
                        # Check for activation phrase
                        if self.activation_phrase in text:
                            # Remove activation phrase for command processing
                            command = text.replace(self.activation_phrase, "").strip()
                            self._process_command(command)
                        
                    except sr.UnknownValueError:
                        log_debug("Google Speech Recognition could not understand audio")
                    except sr.RequestError as e:
                        log_error(f"Could not request results from Google Speech Recognition service: {e}")
                
                except Exception as e:
                    log_error(f"Error in voice recognition: {e}")
                    time.sleep(1)  # Pause briefly before trying again
    
    def _process_command(self, command):
        """Process recognized voice command"""
        log_info(f"Processing command: {command}")
        
        # Check special commands first
        for key, handler in self.special_commands.items():
            if key in command:
                handler(command)
                return
        
        # Check control actions
        for phrase, action in self.command_map.items():
            if phrase in command:
                log_info(f"Executing action: {action}")
                control_manager.execute_action(action, source="voice")
                self.speak(f"Executing {phrase}", f"confirm_{phrase}")
                return
        
        # If no command matched
        log_warning(f"Unrecognized command: {command}")
        self.speak("I'm sorry, I didn't understand that command", "unknown_command")
    
    def _handle_hello(self, command):
        """Handle hello command"""
        self.speak("Hello! I'm Trilobot. How can I help you today?", "hello")
    
    def _handle_status(self, command):
        """Handle status command"""
        movement = state_tracker.get_state('movement')
        led_mode = state_tracker.get_state('led_mode')
        
        status_text = f"I am currently {movement}. "
        
        if led_mode != 'off':
            status_text += f"My LED mode is set to {led_mode}. "
        
        self.speak(status_text, "status_report")
    
    def _handle_who_are_you(self, command):
        """Handle identity questions"""
        self.speak(
            "I am Trilobot, a robotic platform built with a Raspberry Pi. "
            "I can move around, detect objects, and respond to voice commands. "
            "I'm here to assist and entertain you!",
            "identity"
        )
    
    def _handle_help(self, command):
        """Handle help command"""
        help_text = (
            "I can respond to commands like: move forward, move backward, "
            "turn left, turn right, stop, take photo, party mode, and more. "
            "You can also ask me about my status or who I am."
        )
        self.speak(help_text, "help")

# Create global voice controller instance
voice_controller = VoiceController() 