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
                    log_warning(f"Skipping mic index {mic_index} ({mic_name}): {e}")
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
            # Use a slight delay before speaking to ensure thread starts
            time.sleep(0.5)
            self.speak("Voice control activated", "startup")
            return True
        except Exception as e:
            log_error(f"Error starting voice recognition: {e}", exc_info=True)
            return False
    
    def stop(self):
        """Stop voice recognition"""
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.stop_recognition.set()
            self.recognition_thread.join(timeout=2.0) # Increased timeout slightly
            if self.recognition_thread.is_alive():
                 log_warning("Voice recognition thread did not exit cleanly.")
            else:
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
                with open(cache_file, "wb") as f:
                    # Iterate over chunks if it's a streaming response (though convert should return bytes)
                    if hasattr(audio_bytes, '__iter__') and not isinstance(audio_bytes, bytes):
                         log_debug("Received streaming audio data, writing chunks...")
                         for chunk in audio_bytes:
                              if chunk:
                                   f.write(chunk)
                    elif isinstance(audio_bytes, bytes):
                         log_debug("Received bytes audio data, writing directly...")
                         f.write(audio_bytes)
                    else:
                         raise TypeError(f"Unexpected audio data type from ElevenLabs: {type(audio_bytes)}")
                         
                log_debug(f"Generated TTS audio and saved to {cache_file}")

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

    def _recognition_loop(self):
        """Main loop for listening and processing voice commands"""
        if not self.microphone or not self.recognizer:
            log_error("Recognition loop cannot start: mic or recognizer not initialized.")
            return
            
        log_info("Voice recognition loop started")
        active_listening = False # Flag to track if activation phrase was heard
        last_active_time = 0
        timeout_duration = config.get("voice", "timeout_duration") or 10 # Removed fallback

        while not self.stop_recognition.is_set():
            log_debug("Listening for audio...")
            with self.microphone as source:
                try:
                    # Listen for audio input
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                except sr.WaitTimeoutError:
                    log_debug("No speech detected in timeout period.")
                    # Check if we were actively listening and timed out
                    if active_listening and (time.time() - last_active_time > timeout_duration):
                         log_info("Command listening timed out.")
                         active_listening = False
                    continue
                except Exception as listen_e:
                     log_error(f"Error during audio listening: {listen_e}")
                     time.sleep(1) # Avoid busy-looping on persistent errors
                     continue

            try:
                # Recognize speech using Google Web Speech API
                text = self.recognizer.recognize_google(audio).lower()
                log_info(f"Voice received: '{text}'")

                # Check for activation phrase if not already listening
                if not active_listening:
                    if self.activation_phrase in text:
                        log_info("Activation phrase detected!")
                        active_listening = True
                        last_active_time = time.time()
                        # Optional: Provide audio feedback
                        self.speak("Yes?", "activation_confirm") 
                        # Process command immediately if activation phrase was the only thing said
                        command_part = text.replace(self.activation_phrase, "").strip()
                        if command_part:
                             self._process_command(command_part)
                        else:
                             log_info("Waiting for command after activation...")
                    else:
                        log_debug("Ignoring speech (activation phrase not detected).")
                else:
                    # Already actively listening, process the command
                    self._process_command(text)
                    # Reset active listening after processing a command
                    active_listening = False 
                    
            except sr.UnknownValueError:
                log_warning("Could not understand audio")
                if active_listening:
                     # Maybe provide feedback if we were expecting a command
                     # self.speak("Sorry, I didn't catch that.", "unknown_value")
                     # Consider resetting active_listening here too, or keep listening briefly?
                     pass 
            except sr.RequestError as e:
                log_error(f"Could not request results from Google Speech Recognition service; {e}")
                # Might indicate network issues
                active_listening = False # Reset on network error
            except Exception as recog_e:
                 log_error(f"Error during voice recognition processing: {recog_e}", exc_info=True)
                 active_listening = False # Reset on unexpected errors

        log_info("Voice recognition loop finished.")

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

# Singleton instance
voice_controller = VoiceController() 