# Trilobot Bot

A Python-based project for controlling Pimoroni's Trilobot robot with a PlayStation 4 controller and a Raspberry Pi. Includes features like Knight Rider-style LED animations, camera streaming, and distance-based lighting effects.

## Features
- **PS4 Controller Support**: Control Trilobot using a wireless PS4 controller with tank steering or arcade steering modes.
- **Knight Rider Effect**: LED animations reminiscent of KITT from Knight Rider.
- **Party Mode**: Fun light effects with vibrant colors.
- **Distance Sensor Integration**: LED lights react to proximity of obstacles.
- **Camera Streaming**: Stream video from the Pi camera module to a web browser.

## Requirements
- Raspberry Pi 4 or newer
- Pimoroni Trilobot
- Raspberry Pi Camera Module (or compatible)
- Python 3.8 or newer
- PS4 Wireless Controller
- [Picamera2](https://github.com/raspberrypi/picamera2) library for video streaming
- Network connection for accessing the camera stream

## Installation
1. Clone this repository to your Raspberry Pi:
   ```bash
   git clone https://github.com/DanDon01/Trilobot-bot.git
   cd Trilobot-bot

2. Install dependencies:

   sudo apt update && sudo apt install -y python3 python3-pip
   pip3 install -r requirements.txt

3. Run the main script:

   python3 main.py

## Usage

1. Pair your PS4 controller with the Raspberry Pi via Bluetooth.

2. Start the script:
   python3 main.py

3. Access the camera stream in your browser:
   http://<your-pi-ip>:8000

## Known Issues
Ensure the camera is properly connected before starting the script.
PS4 controller pairing can sometimes require multiple attempts.

