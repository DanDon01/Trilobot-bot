from flask import Flask, render_template, jsonify
from trilobot import Trilobot
import threading
import time

app = Flask(__name__)
tbot = Trilobot()

# Configuration
SPEED = 0.6  # 60% speed for safety
control_lock = threading.Lock()  # Local lock for web control

@app.route('/')
def index():
    """Serve the main control page"""
    return render_template('index.html')

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands"""
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
        'status': 'web_control_active'
    })

# Cleanup function
def cleanup():
    tbot.disable_motors()
    tbot.clear_underlighting()

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        cleanup()