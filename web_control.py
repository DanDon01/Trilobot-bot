from flask import Flask, render_template, jsonify
from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT
from trilobot import LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
import threading
import time

app = Flask(__name__)
tbot = Trilobot()

# Configuration
SPEED = 0.6  # 60% speed for safety
control_lock = threading.Lock()

# Light show constants
KNIGHT_RIDER_INTERVAL = 0.1
PARTY_MODE_INTERVAL = 0.2

# Colors
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
MAGENTA = (255, 0, 255)
CYAN = (0, 255, 255)

# Light mapping for effects
KNIGHT_RIDER_MAPPING = [
    LIGHT_REAR_LEFT,
    LIGHT_MIDDLE_LEFT,
    LIGHT_FRONT_LEFT,
    LIGHT_FRONT_RIGHT,
    LIGHT_MIDDLE_RIGHT,
    LIGHT_REAR_RIGHT
]

PARTY_COLORS = [
    RED,        # Red
    GREEN,      # Green
    BLUE,       # Blue
    YELLOW,     # Yellow
    MAGENTA,    # Magenta
    CYAN,       # Cyan
    (255, 128, 0),  # Orange
    (128, 0, 255),  # Purple
]

# Global state
button_leds_active = False
knight_rider_active = False
party_mode_active = False
tank_mode_active = False
light_show_thread = None
stop_light_shows = threading.Event()

# Add these global variables at the top
current_speeds = {'left': 0, 'right': 0}
is_moving = False
ACCELERATION = 0.1  # For smooth speed changes

def knight_rider_effect():
    """Run the Knight Rider light effect"""
    current_led = 0
    direction = 1
    
    while not stop_light_shows.is_set() and knight_rider_active:
        tbot.clear_underlighting(show=False)
        tbot.set_underlight(KNIGHT_RIDER_MAPPING[current_led], RED, show=True)
        
        # Update LED position
        current_led += direction
        
        # Change direction at ends
        if current_led >= len(KNIGHT_RIDER_MAPPING) - 1:
            current_led = len(KNIGHT_RIDER_MAPPING) - 2
            direction = -1
        elif current_led <= 0:
            current_led = 1
            direction = 1
            
        time.sleep(KNIGHT_RIDER_INTERVAL)

def party_mode_effect():
    """Run the party mode light effect"""
    color_index = 0
    
    while not stop_light_shows.is_set() and party_mode_active:
        tbot.fill_underlighting(PARTY_COLORS[color_index])
        color_index = (color_index + 1) % len(PARTY_COLORS)
        time.sleep(PARTY_MODE_INTERVAL)

def start_light_show(effect_function):
    """Start a light show in a separate thread"""
    global light_show_thread
    
    # Stop any running light shows
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join()
    
    # Reset the stop event and start new light show
    stop_light_shows.clear()
    light_show_thread = threading.Thread(target=effect_function)
    light_show_thread.start()

@app.route('/')
def index():
    """Serve the main control page"""
    return render_template('index.html')

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands with smooth acceleration"""
    global current_speeds, is_moving
    
    try:
        if action == 'start':
            is_moving = True
            speed = SPEED if not tank_mode_active else SPEED * 0.7
            
            if direction == 'forward':
                target_speeds = {'left': speed, 'right': speed}
            elif direction == 'backward':
                target_speeds = {'left': -speed, 'right': -speed}
            elif direction == 'left':
                if tank_mode_active:
                    target_speeds = {'left': -speed, 'right': speed}
                else:
                    target_speeds = {'left': -speed/2, 'right': speed/2}
            elif direction == 'right':
                if tank_mode_active:
                    target_speeds = {'left': speed, 'right': -speed}
                else:
                    target_speeds = {'left': speed/2, 'right': -speed/2}
                    
            # Smoothly adjust speeds
            while is_moving and any(abs(current_speeds[motor] - target_speeds[motor]) > 0.01 for motor in ['left', 'right']):
                for motor in ['left', 'right']:
                    diff = target_speeds[motor] - current_speeds[motor]
                    if abs(diff) > ACCELERATION:
                        current_speeds[motor] += ACCELERATION if diff > 0 else -ACCELERATION
                    else:
                        current_speeds[motor] = target_speeds[motor]
                
                # Apply the new speeds
                tbot.set_left_speed(current_speeds['left'])
                tbot.set_right_speed(current_speeds['right'])
                time.sleep(0.02)  # Small delay for smooth acceleration
                
        elif action == 'stop':
            is_moving = False
            # Smoothly stop
            while any(abs(current_speeds[motor]) > 0.01 for motor in ['left', 'right']):
                for motor in ['left', 'right']:
                    if abs(current_speeds[motor]) > ACCELERATION:
                        current_speeds[motor] -= ACCELERATION if current_speeds[motor] > 0 else -ACCELERATION
                    else:
                        current_speeds[motor] = 0
                
                tbot.set_left_speed(current_speeds['left'])
                tbot.set_right_speed(current_speeds['right'])
                time.sleep(0.02)
            
            tbot.disable_motors()
            current_speeds = {'left': 0, 'right': 0}
            
        return jsonify({
            'status': 'success',
            'direction': direction,
            'action': action,
            'speeds': current_speeds
        })
        
    except Exception as e:
        is_moving = False
        tbot.disable_motors()
        current_speeds = {'left': 0, 'right': 0}
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/toggle/<mode>')
def toggle_mode(mode):
    """Toggle various modes and features"""
    global button_leds_active, knight_rider_active, party_mode_active, tank_mode_active
    
    try:
        if mode == 'knight':
            knight_rider_active = not knight_rider_active
            party_mode_active = False
            
            if knight_rider_active:
                start_light_show(knight_rider_effect)
            else:
                stop_light_shows.set()
                tbot.clear_underlighting()
                
            return jsonify({'status': 'success', 'active': knight_rider_active})
            
        elif mode == 'party':
            party_mode_active = not party_mode_active
            knight_rider_active = False
            
            if party_mode_active:
                start_light_show(party_mode_effect)
            else:
                stop_light_shows.set()
                tbot.clear_underlighting()
                
            return jsonify({'status': 'success', 'active': party_mode_active})
            
        elif mode == 'tank':
            tank_mode_active = not tank_mode_active
            return jsonify({'status': 'success', 'active': tank_mode_active})
            
        elif mode == 'leds':
            button_leds_active = not button_leds_active
            for led in range(NUM_BUTTONS):
                tbot.set_button_led(led, button_leds_active)
            return jsonify({'status': 'success', 'active': button_leds_active})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/status')
def get_status():
    """Get current status of all modes"""
    return jsonify({
        'knight_rider': knight_rider_active,
        'party_mode': party_mode_active,
        'tank_mode': tank_mode_active,
        'button_leds': button_leds_active
    })

def cleanup():
    """Cleanup function to run when shutting down"""
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join()
    tbot.disable_motors()
    tbot.clear_underlighting()
    for led in range(NUM_BUTTONS):
        tbot.set_button_led(led, False)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        cleanup()