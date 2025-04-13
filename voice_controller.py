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
import hashlib

# Import local modules
from debugging import log_info, log_error, log_warning, log_debug, state_tracker
from config import config
from control_manager import control_manager, ControlAction

logger = logging.getLogger('trilobot.voice')

# Check if voice modules are available
SPEECH_RECOGNITION_AVAILABLE = False
ELEVENLABS_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
    logger.info("Successfully imported SpeechRecognition.")
except ImportError as e_imp:
    # This is the expected error if the package is just missing
    logger.warning(f"ImportError for SpeechRecognition: {e_imp}. Voice recognition disabled.")
except Exception as e_gen:
    # This catches other errors during import (e.g., dependencies missing)
    logger.error(f"FAILED to import SpeechRecognition due to an unexpected error: {e_gen}. Voice recognition disabled.", exc_info=True)

try:
    from elevenlabs import generate, save, set_api_key, voices, Voice
    # from elevenlabs.api import History # History might not be needed directly, keep it simpler
    ELEVENLABS_AVAILABLE = True
    logger.info("Successfully imported ElevenLabs.")
except ImportError as e_imp:
    # Expected error if package is missing
    logger.warning(f"ImportError for ElevenLabs: {e_imp}. Voice synthesis disabled.")
except Exception as e_gen:
    # Catch other errors during import
    logger.error(f"FAILED to import ElevenLabs due to an unexpected error: {e_gen}. Voice synthesis disabled.", exc_info=True)

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
        self.audio_available = False
        try:
            pygame.mixer.init()
            self.audio_available = True
        except pygame.error as e:
            log_warning(f"Failed to initialize audio: {e}")
            log_warning("Voice synthesis (speech output) will be disabled")
        
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
            api_key = config.get("voice", "elevenlabs_api_key")
            if api_key:
                set_api_key(api_key)
                log_info("ElevenLabs API key configured from config file")
            else:
                log_warning("ElevenLabs API key not found in configuration")
        
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
    
    def speak(self, text, cache_key=None):
        """Speak the given text using TTS"""
        if not self.enabled or not self.audio_available:
            log_debug(f"Voice output disabled, not speaking: {text}")
            return
            
        # Use provided cache key or the text itself for caching
        if cache_key is None:
            cache_key = text
            
        # Cache handling
        cache_file = os.path.join(self.cache_dir, hashlib.md5(cache_key.encode()).hexdigest() + ".mp3")
        
        # If not in cache, generate it (if possible)
        if not os.path.exists(cache_file) and ELEVENLABS_AVAILABLE:
            try:
                # Get the voice name and ID from config
                voice_name = config.get("voice", "elevenlabs_voice_id")
                voice_id = None
                
                # Look up the voice ID from the voices dictionary
                voices_dict = config.get("voice", "elevenlabs_voices")
                if voice_name in voices_dict:
                    voice_id = voices_dict[voice_name]
                else:
                    # Fallback to the name as the ID directly if not found in mapping
                    voice_id = voice_name
                    
                log_debug(f"Using ElevenLabs voice: {voice_name} (ID: {voice_id})")
                
                # Generate audio with ElevenLabs
                api_key = config.get("voice", "elevenlabs_api_key")
                if api_key:
                    audio = generate(
                        text=text,
                        voice=Voice(voice_id=voice_id),
                        model="eleven_monolingual_v1"
                    )
                    
                    with open(cache_file, "wb") as f:
                        f.write(audio)
                    log_debug(f"Generated TTS audio and saved to {cache_file}")
                else:
                    log_warning("No ElevenLabs API key configured, cannot generate audio")
            except Exception as e:
                log_error(f"Failed to generate TTS for: {text} - {e}")
                return
        
        # If the file exists now, play it
        if os.path.exists(cache_file):
            self._play_audio(cache_file)
        else:
            log_warning(f"No TTS cache file available for: {text}")
            
    def _play_audio(self, file_path):
        """Play the audio file at the given path"""
        if not self.audio_available:
            log_debug(f"Audio playback not available, cannot play: {file_path}")
            return
            
        try:
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            
            # Wait for the audio to finish playing
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        except Exception as e:
            log_error(f"Failed to play audio file {file_path}: {e}")
    
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