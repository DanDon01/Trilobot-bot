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
import tempfile
import hashlib
import shutil
import stat
from enum import Enum
import platform

# These environment variables are now set in main.py, but we'll include them here as well
# for when voice_controller is run directly in testing
if 'PYGAME_HIDE_SUPPORT_PROMPT' not in os.environ:
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'  # Hide pygame welcome message
# Removed ALSA_OUTPUT_GIVE_UP
    # Removed ALSA audio environment variable

# We no longer need to do stderr redirection here since main.py handles it globally
# But we'll import pygame here to ensure it's loaded with the environment variables set
import pygame

# Import local modules
from debugging import log_info, log_error, log_warning, log_debug, state_tracker, safe_log
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

# Only try to import speech_recognition on Linux platforms
# Windows compatibility is limited and prone to errors
if platform.system() != 'Windows':
    try:
        import speech_recognition as sr
        # Just test if we can import it, but don't initialize any audio devices yet
        SPEECH_RECOGNITION_AVAILABLE = True
        safe_log(logger, 'info', "Successfully imported SpeechRecognition.")
    except ImportError as e_imp:
        # This is the expected error if the package is just missing
        safe_log(logger, 'warning', f"ImportError for SpeechRecognition: {e_imp}. Voice recognition disabled.")
    except Exception as e_gen:
        # This catches other errors during import (e.g., dependencies missing)
        safe_log(logger, 'error', f"FAILED to import SpeechRecognition due to an unexpected error: {e_gen}. Voice recognition disabled.")
        sr = None
else:
    safe_log(logger, 'warning', "Voice recognition not supported on Windows platform.")
    sr = None

try:
    # *** Import the client class ***
    from elevenlabs.client import ElevenLabs
    ELEVENLABS_AVAILABLE = True
    safe_log(logger, 'info', "Successfully imported ElevenLabs client.")
except ImportError as e_imp:
    safe_log(logger, 'warning', f"ImportError for ElevenLabs client: {e_imp}. Could be missing package. Voice synthesis disabled.")
    # Do not modify global ELEVENLABS_AVAILABLE here
    # self.eleven_client will remain None, which prevents usage
except Exception as e_gen:
    safe_log(logger, 'error', f"FAILED to import ElevenLabs client due to an unexpected error: {e_gen}. Voice synthesis disabled.")
    # Do not modify global ELEVENLABS_AVAILABLE here
    # self.eleven_client will remain None, which prevents usage

class VoiceController:
    """Controls voice recognition and TTS for the Trilobot"""
    
    def __init__(self):
        """Initialize the voice controller with the given configuration"""
        self.stop_event = threading.Event()
        self.status = VoiceStatus.IDLE
        self.status_lock = threading.Lock()
        self.is_running = False
        self.audio_available = False
        self.microphone = None
        self.recognition_thread = None
        
        # Platform compatibility check
        self.is_compatible_platform = platform.system() != 'Windows'
        if not self.is_compatible_platform:
            log_warning("Voice controller not fully supported on Windows platform")
        
        self.wake_words = ["hey trilobot", "hey robot", "hey tri bot", "hey jonny 4", "robot", "commander"]
        
        # Get voice config
        self.enabled = config.get('voice', 'enabled') if config.get('voice', 'enabled') is not None else False
        if not self.enabled:
            log_info("Voice control is disabled in configuration")
            return
            
        # Initialize speech recognition - but only on compatible platforms
        if self.is_compatible_platform and sr:
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
            log_warning(f"SpeechRecognition library not available or platform not compatible")
            self.recognizer = None
            
        # Initialize ElevenLabs TTS if available
        self.elevenlabs_api_key = config.get('voice', 'elevenlabs_api_key')
        self.elevenlabs_voice_id = config.get('voice', 'elevenlabs_voice_id') or 'premade/adam'
        self.tts_initialized = False
        
        if not self.elevenlabs_api_key:
            log_warning("ElevenLabs API key not provided in configuration")
        else:
            try:
                if ELEVENLABS_AVAILABLE:
                    # Don't use elevenlabs.set_api_key() as it's not defined
                    # The client will be initialized later with the API key
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
            # We only use pygame for playback, not VLC
            log_info("Audio playback will use pygame")
        except Exception as e:
            log_error(f"Failed to initialize audio playback: {e}")
        
        self.volume = config.get("voice", "volume") / 100.0 if config.get("voice", "volume") is not None else 0.5  # Convert to 0-1 range
        self.activation_phrase = config.get("voice", "activation_phrase") or "hey trilobot"
        self.activation_phrase = self.activation_phrase.lower()
        
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
            # Skip audio initialization on non-compatible platforms
            if not self.is_compatible_platform:
                log_warning("Audio initialization skipped on non-compatible platform")
                self.audio_available = False
            else:
                # Don't set dummy driver, let pygame use the system default
                try:
                    # Initialize pygame mixer with conservative settings to reduce errors
                    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=4096)
                    self.audio_available = True
                    log_info("Audio playback initialized with system default driver")
                except pygame.error as default_error:
                    log_warning(f"Audio initialization failed: {default_error}")
                    self.audio_available = False
        except Exception as e:
            log_warning(f"Failed to initialize audio: {e}")
            log_warning("Voice synthesis (speech output) will be disabled")
            self.audio_available = False
        
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
            return False
            
        # Check platform compatibility first
        if platform.system() == 'Windows':
            log_warning("Voice control not supported on Windows")
            return False
            
        # Check for basic modules
        if not sr or not self.recognizer:
            log_warning("Voice recognition not available - speech_recognition module missing")
            return False
            
        log_info("Starting voice controller...")
        
        # Try to initialize microphone if not already done
        try:
            # Add a protective wrapper around microphone initialization
            # This is where PyAudio/PortAudio often crashes
            try:
                # Add short delay to ensure audio system is ready
                time.sleep(0.5)
                
                # Get list of microphone devices first - this is the risky part
                log_debug("Attempting to get audio device list...")
                available_mics = None
                try:
                    # Try to safely get microphone devices 
                    available_mics = sr.Microphone.list_microphone_names()
                    log_debug(f"Available microphones: {available_mics}")
                except (OSError, IOError, AssertionError) as e:
                    # Common errors when audio devices can't be accessed
                    log_warning(f"Could not list microphones: {e}")
                    return False
                except Exception as e:
                    log_warning(f"Unexpected error listing microphones: {e}")
                    return False
                    
                # Only continue if we could list devices successfully
                if available_mics is None or len(available_mics) == 0:
                    log_warning("No microphones found")
                    return False
                
                # Try to initialize the default microphone
                self.microphone = sr.Microphone()
                log_info("Microphone initialized")
                
                # Adjust for ambient noise - but catch errors here too
                try:
                    with self.microphone as source:
                        log_info("Adjusting for ambient noise...")
                        self.recognizer.adjust_for_ambient_noise(source, duration=1)
                        log_info(f"Energy threshold set to {self.recognizer.energy_threshold}")
                except Exception as noise_e:
                    log_error(f"Failed to adjust for ambient noise: {noise_e}")
                    return False
            except (OSError, IOError, AssertionError) as e:
                log_error(f"Audio device error: {e}")
                return False
            except Exception as e:
                log_error(f"Failed to initialize microphone: {e}")
                return False
                
            # Start recognition thread
            self.stop_event.clear()
            self.recognition_thread = threading.Thread(target=self._recognize_continuously)
            self.recognition_thread.daemon = True
            self.recognition_thread.start()
            self.is_running = True
            log_info("Voice recognition started")
            return True
            
        except Exception as e:
            log_error(f"Unexpected error starting voice controller: {e}")
            return False

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
        detected_wake_word = None
        
        # First try exact matching
        for wake_word in self.wake_words:
            if wake_word in text:
                wake_word_detected = True
                detected_wake_word = wake_word
                break
                
        # If no exact match, try fuzzy matching
        if not wake_word_detected:
            # Check if the entire text is close to any wake word
            if text == "commander" or text == "robot":
                wake_word_detected = True
                detected_wake_word = text
                
        if wake_word_detected:
            # Remove wake word from text if present
            if detected_wake_word and detected_wake_word in text:
                command = text.replace(detected_wake_word, "").strip()
            else:
                command = text.strip()
                
            log_info(f"Wake word detected: '{detected_wake_word}', command: '{command}'")
            
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
                control_manager.execute_action(ControlAction.STOP, source="voice")
            elif "forward" in command:
                self.speak("Moving forward.")
                control_manager.execute_action(ControlAction.MOVE_FORWARD, source="voice")
            elif "backward" in command or "back" in command:
                self.speak("Moving backward.")
                control_manager.execute_action(ControlAction.MOVE_BACKWARD, source="voice")
            elif "left" in command:
                self.speak("Turning left.")
                control_manager.execute_action(ControlAction.TURN_LEFT, source="voice")
            elif "right" in command:
                self.speak("Turning right.")
                control_manager.execute_action(ControlAction.TURN_RIGHT, source="voice")
            elif "photo" in command or "picture" in command or "snapshot" in command:
                self.speak("Taking a photo.")
                control_manager.execute_action(ControlAction.TAKE_PHOTO, source="voice")
            elif "party" in command:
                self.speak("Party mode activated!")
                control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE, source="voice")
            elif "knight" in command or "rider" in command:
                self.speak("Knight Rider mode activated!")
                control_manager.execute_action(ControlAction.TOGGLE_KNIGHT_RIDER, source="voice")
            elif "led" in command or "light" in command:
                self.speak("Toggling LEDs.")
                control_manager.execute_action(ControlAction.TOGGLE_LIGHT, source="voice")
            else:
                self.speak(f"I heard you say {command}, but I don't know how to handle that command.")
            
            # Reset status
            with self.status_lock:
                self.status = VoiceStatus.IDLE
        else:
            # No wake word detected
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
                voice_name = config.get("voice", "elevenlabs_voice_id") or "Josh"
                
                model_id = config.get("voice", "elevenlabs_model_id") or "eleven_multilingual_v2"
                
                output_format = config.get("voice", "elevenlabs_output_format") or "mp3_44100_128"
                
                voice_id = None
                
                # Look up the voice ID from the voices dictionary if provided
                voices_dict = config.get("voice", "elevenlabs_voices") or {}
                
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
        text = text.lower()
        return (target in text or 
                text in target or 
                any(part in text for part in target.split() if len(part) > 2))

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
voice_controller = VoiceController() 
