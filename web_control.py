from flask import Flask, render_template, jsonify
from trilobot import Trilobot
import time

app = Flask(__name__)
tbot = Trilobot()

# Movement speeds
SPEED = 0.6  # 60% speed for safety

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/move/<direction>')
def move(direction):
    try:
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
        elif direction == 'stop':
            tbot.disable_motors()
        
        time.sleep(0.1)  # Brief movement
        tbot.disable_motors()  # Safety stop
        
        return jsonify({'status': 'success', 'direction': direction})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)