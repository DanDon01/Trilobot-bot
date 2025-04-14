# Trilobot Robot

A Python-based project for controlling Pimoroni's Trilobot robot with a PlayStation 4 controller, web interface, voice commands, and computer vision capabilities.

## Features

- **Unified Control System**: Seamlessly switch between PS4 controller, web interface, and voice commands
- **PS4 Controller Support**: Control Trilobot using a wireless PS4 controller with tank steering
- **Web Interface**: Browser-based control panel with live camera feed and status indicators
- **Voice Control**: Command your Trilobot using natural language with ElevenLabs voice synthesis
- **Computer Vision**: Object detection and tracking capabilities
- **LED Effects**: Knight Rider animation, party mode, and context-aware lighting
- **Distance Sensing**: Automatic obstacle detection and avoidance
- **Modular Architecture**: Easy to extend with new features

## Requirements

### Hardware
- Raspberry Pi 4 (2GB RAM or higher recommended)
- Pimoroni Trilobot robot platform
- Raspberry Pi Camera Module
- PS4 Wireless Controller (optional)
- USB Microphone (for voice control, optional)
- Speaker (for voice responses, optional)

### Software
- Python 3.8 or newer
- Required Python packages listed in `requirements.txt`
- ElevenLabs API key (for voice synthesis, optional)
- TensorFlow Lite models (for computer vision, optional)

## Installation

1. Clone this repository to your Raspberry Pi:
   ```bash
   git clone https://github.com/yourusername/trilobot-project.git
   cd trilobot-project
   ```

2. Set up a Python virtual environment:
   ```bash
   # Install venv if not already installed
   sudo apt-get update
   sudo apt-get install -y python3-venv

   # Create a virtual environment
   python3 -m venv venv

   # Activate the virtual environment
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   # Make sure you're in the virtual environment (should see (venv) in prompt)
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Configure settings (optional):
   Edit `config.json` to customize settings or use the defaults.
   
   For ElevenLabs voice synthesis, set your API key:
   ```bash
   export ELEVENLABS_API_KEY=your_api_key_here
   ```

5. Run the application:
   ```bash
   python main.py
   ```

## Usage

### Web Interface
Access the web control interface at `http://<raspberry-pi-ip>:5000`

### PS4 Controller
- **Left/Right Sticks**: Tank-style movement controls
- **Triangle**: Toggle button LEDs
- **Circle**: Toggle Knight Rider effect
- **Square**: Toggle party mode
- **X**: Emergency stop
- **Share**: Take photo
- **PS Button**: Full emergency stop

### Voice Commands
Say "Hey Trilobot" followed by:
- "Move forward/backward"
- "Turn left/right"
- "Stop"
- "Party mode"
- "Knight Rider"
- "Take photo"
- "Status report"

## Voice Control System

The Trilobot includes a sophisticated voice control system that allows for hands-free operation:

### Core Components

1. **Speech Recognition**: Uses Google's speech recognition service through the `SpeechRecognition` Python library to convert your voice to text.

2. **Text-to-Speech**: Uses ElevenLabs' high-quality voice synthesis API to generate natural-sounding responses.

3. **Command Processing**: Analyzes recognized text to execute robot actions or provide information.

### How It Works

1. **Activation**: The system listens continuously for the phrase "hey trilobot" (your wake word).

2. **Command Mode**: After hearing the wake word, the robot responds with "Yes?" and enters active listening mode for 10 seconds.

3. **Command Execution**: Commands are mapped to robot actions like movement, LED effects, or photo capture.

4. **Response**: The robot provides audio feedback for commands and can answer special queries.

### Available Commands

#### Movement Commands:
- "move forward" / "go forward" / "forward"
- "move backward" / "go backward" / "back up" / "reverse"
- "turn left" / "go left" / "left"
- "turn right" / "go right" / "right"
- "stop" / "halt" / "freeze"
- "emergency stop" / "emergency halt"

#### LED Commands:
- "knight rider" (activates the Knight Rider LED effect)
- "party mode" (activates the party mode LED effect)

#### Camera Commands:
- "take photo" / "take picture" / "capture image"

#### Information Commands:
- "hello" / "hi" / "hey" (gets a greeting response)
- "status" / "status report" (reports on robot's current status)
- "who are you" / "what are you" (tells you about the Trilobot)
- "help" (lists available commands)

### Technical Details

- Voice responses are cached in `/tmp/trilobot_responses` to reduce API usage
- Uses the Josh voice from ElevenLabs by default
- Automatically finds and uses available microphones
- Has a 5-second timeout for listening to commands
- After wake word activation, has a 10-second window to receive commands

### Setting Up Voice Control

1. Install required packages:
   ```bash
   pip install SpeechRecognition elevenlabs pygame pyaudio
   ```

2. Set your ElevenLabs API key in `config.json`:
   ```json
   "voice": {
       "enabled": true,
       "elevenlabs_api_key": "YOUR_API_KEY_HERE"
   }
   ```

3. Make sure a microphone and speaker are connected to your Raspberry Pi

4. Restart the application and say "hey trilobot" followed by a command

## Project Structure

- `main.py` - Main application entry point
- `config.py` - Configuration management
- `debugging.py` - Logging and debugging utilities
- `control_manager.py` - Unified control system
- `web_control.py` - Flask web server
- `camera_processor.py` - Camera and computer vision
- `voice_controller.py` - Speech recognition and synthesis
- `ps4_controller.py` - PS4 controller input handler
- `templates/` - Web interface HTML templates
- `static/` - Web interface static files
- `models/` - TensorFlow Lite models
- `responses/` - Cached voice responses

## Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Pimoroni](https://shop.pimoroni.com/) for the Trilobot platform
- [ElevenLabs](https://elevenlabs.io/) for voice synthesis
- [TensorFlow Lite](https://www.tensorflow.org/lite) for object detection

