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
import shutil
import stat
from enum import Enum

# Import local modules
from debugging import log_info, log_error, log_warning, log_debug, state_tracker
from config import config
from control_manager import control_manager, ControlAction

# We need to import this way to avoid circular imports
# The web_control module is imported only where needed
import sys

logger = logging.getLogger('trilobot.voice')

# Define voice status states
class VoiceStatus(Enum):
    """Status states for the voice recognition system"""
    IDLE = 0
    LISTENING = 1
    PROCESSING = 2
    SPEAKING = 3
    ERROR = 4

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
    # *** Import the client class ***
    from elevenlabs.client import ElevenLabs
    ELEVENLABS_AVAILABLE = True
    logger.info("Successfully imported ElevenLabs client.")
except ImportError as e_imp:
    logger.warning(f"ImportError for ElevenLabs client: {e_imp}. Could be missing package. Voice synthesis disabled.")
    # Do not modify global ELEVENLABS_AVAILABLE here
    # self.eleven_client will remain None, which prevents usage
except Exception as e_gen:
    logger.error(f"FAILED to import ElevenLabs client due to an unexpected error: {e_gen}. Voice synthesis disabled.", exc_info=True)
    # Do not modify global ELEVENLABS_AVAILABLE here
    # self.eleven_client will remain None, which prevents usage

class VoiceController:
    """Controls voice recognition and TTS for the Trilobot"""
    
    def __init__(self, config, control_manager):
        """Initialize the voice controller with the given configuration"""
        self.config = config
        self.control_manager = control_manager
        self.stop_event = threading.Event()
        self.status = VoiceStatus.IDLE
        self.status_lock = threading.Lock()
        self.is_running = False
        
        self.wake_words = ["hey trilobot", "hey robot", "hey tri bot", "hey try bot", "robot"]
        
        # Get voice config
        self.enabled = self.config.get('voice', {}).get('enabled', False)
        if not self.enabled:
            log_info("Voice control is disabled in configuration")
            return
            
        # Initialize speech recognition
        if sr:
            try:
                self.recognizer = sr.Recognizer()
                # Set optimal parameters for Trilobot environment
                self.recognizer.energy_threshold = 3000  # Higher value means less sensitive
                self.recognizer.dynamic_energy_threshold = True
                self.recognizer.dynamic_energy_adjustment_damping = 0.15
                self.recognizer.dynamic_energy_ratio = 1.5
                self.recognizer.pause_threshold = 0.8  # Seconds of silence before considering the phrase complete
                self.recognizer.operation_timeout = 3  # Seconds
                
                log_info("Speech recognition initialized successfully")
            except Exception as e:
                log_error(f"Failed to initialize speech recognition: {e}")
                self.recognizer = None
        else:
            log_warning("SpeechRecognition library not available")
            self.recognizer = None
            
        # Initialize ElevenLabs TTS if available
        self.elevenlabs_api_key = self.config.get('voice', {}).get('elevenlabs_api_key', '')
        self.elevenlabs_voice_id = self.config.get('voice', {}).get('elevenlabs_voice_id', 'premade/adam')
        self.tts_initialized = False
        
        if not self.elevenlabs_api_key:
            log_warning("ElevenLabs API key not provided in configuration")
        else:
            try:
                if elevenlabs:
                    elevenlabs.set_api_key(self.elevenlabs_api_key)
                    self.tts_initialized = True
                    log_info("ElevenLabs TTS initialized successfully")
                else:
                    log_warning("ElevenLabs module not available")
            except Exception as e:
                log_error(f"Failed to initialize ElevenLabs TTS: {e}")
                
        # Initialize cache directory for audio files
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache', 'voice')
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Create media player for audio playback
        self.player = None
        try:
            if vlc:
                self.player = vlc.Instance('--no-video').media_player_new()
                log_info("VLC media player initialized successfully")
            else:
                log_warning("VLC module not available for audio playback")
        except Exception as e:
            log_error(f"Failed to initialize VLC media player: {e}")
        
        self.volume = config.get("voice", "volume") / 100.0  # Convert to 0-1 range
        self.activation_phrase = config.get("voice", "activation_phrase").lower()
        
        # Create cache directory if it doesn't exist
        if not os.path.exists(self.cache_dir):
            try:
                log_info(f"Creating voice responses cache directory: {self.cache_dir}")
                os.makedirs(self.cache_dir, exist_ok=True)
                # Make the directory accessible to all users
                try:
                    # Make sure absolute path exists and is writable
                    os.chmod(self.cache_dir, 0o777)  # Full permissions
                    # Try to write a test file to verify permissions
                    test_file = os.path.join(self.cache_dir, "test_write.txt")
                    with open(test_file, 'w') as f:
                        f.write("Test write successful")
                    os.remove(test_file)  # Clean up test file
                    log_info(f"Successfully verified write permissions for cache directory: {self.cache_dir}")
                except Exception as perm_e:
                    log_warning(f"Could not set permissions on cache directory: {perm_e}")
            except Exception as e:
                log_error(f"Failed to create cache directory: {e}")
                # Fall back to tmp directory if home directory fails
                self.cache_dir = "/tmp/trilobot_responses"
                try:
                    os.makedirs(self.cache_dir, exist_ok=True)
                    os.chmod(self.cache_dir, 0o777)
                    log_info(f"Created fallback cache directory: {self.cache_dir}")
                except Exception as tmp_e:
                    log_error(f"Failed to create even tmp directory: {tmp_e}")
            
        # Initialize pygame for audio playback
        self.audio_available = False
        try:
            pygame.mixer.init()
            self.audio_available = True
        except pygame.error as e:
            log_warning(f"Failed to initialize audio: {e}")
            log_warning("Voice synthesis (speech output) will be disabled")
        
        # Speech recognition components
        self.microphone = None
        self.recognition_thread = None
        
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
        
        # *** Initialize ElevenLabs client ***
        self.eleven_client = None
        if ELEVENLABS_AVAILABLE: # Check if import succeeded globally
            api_key = config.get("voice", "elevenlabs_api_key")
            if api_key:
                try:
                    self.eleven_client = ElevenLabs(api_key=api_key)
                    log_info("ElevenLabs client initialized with API key.")
                    # Optional: Verify connection or list voices here if needed
                    # voices_response = self.eleven_client.voices.get_all()
                    # log_debug(f"Available ElevenLabs voices: {len(voices_response.voices)}")
                except Exception as e:
                    log_error(f"Failed to initialize ElevenLabs client: {e}")
                    # Do not modify global ELEVENLABS_AVAILABLE here
                    # self.eleven_client will remain None, which prevents usage
            else:
                log_warning("ElevenLabs API key not found in configuration. TTS generation will be disabled.")
                # Do not modify global ELEVENLABS_AVAILABLE here
                # self.eleven_client will remain None
        
        log_info("Voice Controller initialized")
        
    def start(self):
        """Start the voice controller"""
        if not self.enabled or self.is_running:
            return
            
        if not sr or not self.recognizer:
            log_warning("Voice recognition not available")
            return
            
        log_info("Starting voice controller...")
        
        # Initialize microphone if not already done
        try:
            # Add short delay to ensure audio system is ready
            time.sleep(0.5)
            self.microphone = sr.Microphone()
            log_info("Microphone initialized")
            
            # Adjust for ambient noise
            with self.microphone as source:
                log_info("Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                log_info(f"Energy threshold set to {self.recognizer.energy_threshold}")
        except Exception as e:
            log_error(f"Failed to initialize microphone: {e}")
            return
            
        # Start recognition thread
        self.stop_event.clear()
        self.recognition_thread = threading.Thread(target=self._recognize_continuously)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
        self.is_running = True
        log_info("Voice recognition started")
        
    def stop(self):
        """Stop the voice controller"""
        if not self.is_running:
            return
            
        log_info("Stopping voice controller...")
        self.stop_event.set()
        
        if self.recognition_thread:
            self.recognition_thread.join(timeout=2)
        
        self.is_running = False
        log_info("Voice controller stopped")

    def _process_speech(self, text):
        """Process recognized speech text"""
        if not text:
            return
            
        text = text.lower().strip()
        log_debug(f"Processing speech: '{text}'")
        
        # Check for wake word
        wake_word_detected = False
        for wake_word in self.wake_words:
            if wake_word in text:
                wake_word_detected = True
                # Remove wake word from text
                command = text.replace(wake_word, "").strip()
                log_info(f"Wake word detected, command: '{command}'")
                
                # Set status to listening
                with self.status_lock:
                    self.status = VoiceStatus.LISTENING
                    
                # Process command
                if not command:
                    self.speak("Yes?")
                    return
                    
                # Check for special commands
                if command in ["hello", "hi"]:
                    self.speak("Hello! I'm Trilobot. How can I help you?")
                elif "status" in command:
                    self.speak("I'm operational and ready for your commands.")
                elif "stop" in command or "halt" in command:
                    self.speak("Stopping all motors.")
                    self.control_manager.execute_action(ControlAction.STOP, source="voice")
                elif "forward" in command:
                    self.speak("Moving forward.")
                    self.control_manager.execute_action(ControlAction.MOVE_FORWARD, source="voice")
                elif "backward" in command or "back" in command:
                    self.speak("Moving backward.")
                    self.control_manager.execute_action(ControlAction.MOVE_BACKWARD, source="voice")
                elif "left" in command:
                    self.speak("Turning left.")
                    self.control_manager.execute_action(ControlAction.TURN_LEFT, source="voice")
                elif "right" in command:
                    self.speak("Turning right.")
                    self.control_manager.execute_action(ControlAction.TURN_RIGHT, source="voice")
                elif "photo" in command or "picture" in command or "snapshot" in command:
                    self.speak("Taking a photo.")
                    self.control_manager.execute_action(ControlAction.TAKE_PHOTO, source="voice")
                elif "party" in command:
                    self.speak("Party mode activated!")
                    self.control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE, source="voice")
                elif "knight" in command or "rider" in command:
                    self.speak("Knight Rider mode activated!")
                    self.control_manager.execute_action(ControlAction.TOGGLE_KNIGHT_RIDER, source="voice")
                elif "led" in command or "light" in command:
                    self.speak("Toggling LEDs.")
                    self.control_manager.execute_action(ControlAction.TOGGLE_LEDS, source="voice")
                else:
                    self.speak(f"I heard you say {command}, but I don't know how to handle that command.")
                
                # Reset status
                with self.status_lock:
                    self.status = VoiceStatus.IDLE
                break
                
        if not wake_word_detected:
            log_debug("No wake word detected in speech")

    def speak(self, text, cache_key=None):
        """Speak the given text using TTS"""
        if not self.enabled or not self.audio_available:
            log_debug(f"Voice output disabled, not speaking: {text}")
            return
            
        # Record the speech activity for web UI
        try:
            from web_control import record_voice_activity
            record_voice_activity(f"Speaking: \"{text}\"")
        except:
            pass
            
        # Use provided cache key or the text itself for caching
        if cache_key is None:
            cache_key = text
            
        # Cache handling
        cache_file = os.path.join(self.cache_dir, hashlib.md5(cache_key.encode()).hexdigest() + ".mp3")
        
        # If not in cache, try to generate it (if possible)
        # *** Check ELEVENLABS_AVAILABLE flag and client instance ***
        if not os.path.exists(cache_file) and ELEVENLABS_AVAILABLE and self.eleven_client:
            try:
                # Get the voice name and ID from config
                voice_name = config.get("voice", "elevenlabs_voice_id")
                if voice_name is None:
                    voice_name = "Josh"  # Default if not found
                
                model_id = config.get("voice", "elevenlabs_model_id") 
                if model_id is None:
                    model_id = "eleven_multilingual_v2"  # Default if not found
                
                output_format = config.get("voice", "elevenlabs_output_format")
                if output_format is None:
                    output_format = "mp3_44100_128"  # Default if not found
                
                voice_id = None
                
                # Look up the voice ID from the voices dictionary if provided
                voices_dict = config.get("voice", "elevenlabs_voices")
                if voices_dict is None:
                    voices_dict = {}  # Default if not found
                
                if voice_name in voices_dict:
                    voice_id = voices_dict[voice_name]
                else:
                    # Fallback to using the name as the ID directly if not found in mapping
                    # This assumes the name might be a valid voice ID (common case for default voices)
                    voice_id = voice_name
                    
                log_debug(f"Using ElevenLabs: Voice='{voice_name}' (Resolved ID='{voice_id}'), Model='{model_id}', Format='{output_format}'")
                
                # *** Use the client's text_to_speech.convert method ***
                audio_bytes = self.eleven_client.text_to_speech.convert(
                    text=text,
                    voice_id=voice_id, # Pass the resolved voice_id string
                    model_id=model_id,
                    output_format=output_format
                )
                
                # Check if we got audio data
                if not audio_bytes:
                     raise ValueError("ElevenLabs API returned empty audio data.")
                     
                # Save the audio bytes to the cache file
                try:
                    # Create a temporary file first, then move it to ensure atomic write
                    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(cache_file), suffix='.mp3.tmp')
                    log_debug(f"Created temp file at: {temp_path}")
                    
                    # Write the data
                    with os.fdopen(fd, 'wb') as temp_file:
                        # Write data based on its type
                        if hasattr(audio_bytes, '__iter__') and not isinstance(audio_bytes, bytes):
                            log_debug("Received streaming audio data, writing chunks...")
                            for chunk in audio_bytes:
                                if chunk:
                                    temp_file.write(chunk)
                        elif isinstance(audio_bytes, bytes):
                            log_debug("Received bytes audio data, writing directly...")
                            temp_file.write(audio_bytes)
                        else:
                            raise TypeError(f"Unexpected audio data type from ElevenLabs: {type(audio_bytes)}")
                    
                    # Set permissions on the temp file before moving
                    os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)  # 0666
                    
                    # Move the temp file to the target location
                    shutil.move(temp_path, cache_file)
                    log_debug(f"Generated TTS audio and saved to {cache_file}")
                    
                except Exception as file_e:
                    log_error(f"Failed to save audio file: {file_e}", exc_info=True)

            except Exception as e:
                log_error(f"Failed to generate TTS using ElevenLabs client for: '{text}' - {e}", exc_info=True)
                # Don't return here, still try to play if file somehow exists or was created partially
                
        elif not os.path.exists(cache_file):
            # Log why generation was skipped
            if not ELEVENLABS_AVAILABLE:
                log_warning(f"TTS generation skipped: ElevenLabs not available (check imports/API key). (ELEVENLABS_AVAILABLE={ELEVENLABS_AVAILABLE})")
            elif not self.eleven_client:
                 log_warning(f"TTS generation skipped: ElevenLabs client not initialized (check API key/init). (ELEVENLABS_AVAILABLE={ELEVENLABS_AVAILABLE})")

        # If the file exists now (either cached or just generated), play it
        if os.path.exists(cache_file):
            self._play_audio(cache_file)
        else:
            # This message now covers cases where generation was skipped or failed
            log_warning(f"No TTS cache file found or generated for: '{text}' (Cache Key: {cache_key}) - Playback skipped.")

    def _play_audio(self, file_path):
        """Play an audio file using pygame mixer"""
        if not self.audio_available:
            log_warning("Audio playback unavailable")
            return
        
        try:
            # Ensure mixer is not busy
            while pygame.mixer.music.get_busy():
                log_debug("Mixer busy, waiting...")
                time.sleep(0.1)
                
            log_debug(f"Playing audio: {file_path}")
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()
            
            # Wait for playback to finish (optional, can remove if async is desired)
            # while pygame.mixer.music.get_busy():
            #     time.sleep(0.1)
            # log_debug("Audio playback finished")
                
        except pygame.error as e:
            log_error(f"Error playing audio file {file_path}: {e}")
        except Exception as e:
            log_error(f"Unexpected error during audio playback: {e}", exc_info=True)

    def _recognize_continuously(self):
        """Continuously listen for voice commands"""
        if not sr or not self.recognizer or not hasattr(self, 'microphone'):
            log_error("Speech recognition not properly initialized")
            return
            
        log_info("Starting continuous speech recognition")
        
        # Set initial status
        with self.status_lock:
            self.status = VoiceStatus.IDLE
            
        # Initialize microphone
        try:
            microphone = self.microphone
        except Exception as e:
            log_error(f"Failed to initialize microphone: {e}")
            return
            
        # Recognition loop
        while not self.stop_event.is_set():
            try:
                # Set status to idle
                with self.status_lock:
                    self.status = VoiceStatus.IDLE
                    
                log_debug("Listening for audio...")
                
                # Listen for audio
                with microphone as source:
                    audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=10)
                
                # Recognition started, update status
                with self.status_lock:
                    self.status = VoiceStatus.PROCESSING
                
                log_debug("Audio received, recognizing...")
                
                try:
                    # Recognize speech
                    text = self.recognizer.recognize_google(audio)
                    log_info(f"Voice received: '{text}'")
                    
                    # Process recognized speech
                    self._process_speech(text)
                    
                except sr.UnknownValueError:
                    log_warning("Could not understand audio")
                except sr.RequestError as e:
                    log_error(f"Recognition request error: {e}")
                    # Back off for a few seconds if we get an API error
                    time.sleep(3)
                except Exception as e:
                    log_error(f"Unexpected error in speech recognition: {e}")
                    
                # Reset status to idle
                with self.status_lock:
                    self.status = VoiceStatus.IDLE
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                log_error(f"Error in voice recognition loop: {e}")
                # Back off for a few seconds to avoid tight error loops
                time.sleep(2)
                
        log_info("Speech recognition stopped")

    def _fuzzy_match(self, target, text):
        """Simple fuzzy matching for wake word detection"""
        return target in text or any(
            part in text for part in target.split() if len(part) > 3
        )

    def _process_command(self, command):
        """Process recognized command text"""
        log_info(f"Processing command: '{command}'")
        processed = False
        
        # Check special commands first
        for phrase, handler in self.special_commands.items():
            if command == phrase:
                handler(command)
                processed = True
                break
        
        if processed: return
        
        # Check mapped control actions
        for phrase, action in self.command_map.items():
            if command == phrase:
                log_info(f"Executing action: {action.name} from voice command: '{command}'")
                control_manager.execute_action(action, source="voice")
                processed = True
                break
                
        if not processed:
            log_warning(f"Unknown command: '{command}'")
            # Optional: Provide feedback for unknown commands
            self.speak(f"Sorry, I don't understand '{command}'.", f"unknown_cmd_{command[:20]}")

    def _handle_hello(self, command):
        self.speak("Hello there!", "hello_reply")

    def _handle_status(self, command):
        # Gather some basic status
        # TODO: Get more detailed status from state_tracker or other modules
        control_mode = state_tracker.get_state("control_mode")
        movement = state_tracker.get_state("movement")
        camera_mode = state_tracker.get_state("camera_mode")
        response = f"Current control mode is {control_mode}. Movement is {movement}. Camera is in {camera_mode} mode."
        self.speak(response, "status_reply")

    def _handle_who_are_you(self, command):
        response = "I am Trilobot, a robot controlled by this Raspberry Pi."
        self.speak(response, "who_are_you_reply")

    def _handle_help(self, command):
        # List some basic commands
        basic_commands = ["move forward", "turn left", "stop", "knight rider", "take photo", "status"]
        response = f"You can ask me to: {', '.join(basic_commands)}. Say '{self.activation_phrase}' first if I'm not listening."
        self.speak(response, "help_reply")

    def _initialize_audio(self):
        """Initialize the audio system and test microphone"""
        try:
            # Initialize recognizer with adjusted parameters
            self.recognizer = sr.Recognizer()
            
            # Set initial energy threshold higher for better wake word detection
            self.recognizer.energy_threshold = 3000
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.dynamic_energy_adjustment_damping = 0.15
            self.recognizer.dynamic_energy_ratio = 1.5
            self.recognizer.pause_threshold = 0.8
            self.recognizer.phrase_threshold = 0.3
            
            # Test microphone availability
            with sr.Microphone() as source:
                log_debug(f"Microphone: {source.device_index}, sample rate: {source.SAMPLE_RATE}")
                log_info("Testing microphone...")
                
                # Adjust for ambient noise
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                log_debug(f"Energy threshold set to {self.recognizer.energy_threshold}")
                
                return True
                
        except Exception as e:
            log_error(f"Error initializing audio: {e}", exc_info=True)
            return False

# Singleton instance
voice_controller = VoiceController(config, control_manager) 