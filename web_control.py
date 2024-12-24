from flask import Flask, render_template, jsonify
from trilobot import Trilobot
import time
import threading

# Initialize Flask app and Trilobot
app = Flask(__name__)
tbot = Trilobot()

# Configuration
SPEED = 0.6  # 60% speed for safety
is_moving = False  # Flag to track movement state
movement_lock = threading.Lock()  # Thread safety for movement control

# Store the current movement state
current_movement = {
    'direction': None,
    'is_active': False
}

@app.route('/')
def index():
    """Serve the main control page"""
    return render_template('index.html')

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands"""
    global control_mode
    
    with control_lock:
        control_mode = 'web'  # Switch to web control
        try:
            if action == 'start':
                if direction == 'forward':
                    tbot.set_left_speed(SPEED)
                    tbot.set_right_speed(SPEED)
                elif direction == 'backward':
                    tbot.set_left_speed(-SPEED)
                    tbot.set_right_speed(-SPEED)
                elif direction == 'left':
                    tbot.set_left_speed(-SPEED)
                    tbot.set_right_speed(SPEED)
                elif direction == 'right':
                    tbot.set_left_speed(SPEED)
                    tbot.set_right_speed(-SPEED)
            elif action == 'stop':
                tbot.disable_motors()
                control_mode = 'ps4'  # Return control to PS4
                
            return jsonify({
                'status': 'success',
                'direction': direction,
                'action': action
            })
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

@app.route('/status')
def get_status():
    """Get current control mode status"""
    return jsonify({
        'control_mode': control_mode,
        'is_ps4_connected': True  # You'll need to modify this based on your controller status
    })

if __name__ == '__main__':
    # Run Flask app on all interfaces (0.0.0.0) so it's accessible from other devices
    app.run(host='0.0.0.0', port=5000, debug=True)