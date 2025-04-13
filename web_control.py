"""
Web Control for Trilobot

This module provides a Flask web server for controlling the Trilobot via a browser.
It includes movement controls, LED controls, and camera streaming.
"""

from flask import Flask, render_template, jsonify, Response
import threading
import time
import io
import os
import logging
from threading import Condition

# Import local modules
from debugging import log_info, log_error, log_warning, state_tracker, log_debug
from config import config
from control_manager import control_manager, ControlMode, ControlAction
from camera_processor import camera_processor

logger = logging.getLogger('trilobot.web')

# Try to import hardware-specific modules
try:
    from trilobot import Trilobot, NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
    hardware_available = True
except ImportError:
    # Mock for development without hardware
    hardware_available = False
    logger.warning("Hardware-specific modules not available. Using mock objects.")
    
    # Define constants that would normally be from trilobot
    NUM_BUTTONS = 6
    LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT = 0, 1
    LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT = 2, 3
    LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT = 4, 5

# Initialize Flask
app = Flask(__name__)

# Global variables
overlay_mode = 'normal'
button_states = {
    'triangle': False,
    'circle': False,
    'cross': False,
    'square': False
}

# Light show thread
light_show_thread = None
stop_light_shows = threading.Event()

@app.route('/')
def index():
    """Serve the main page"""
    # Get hardware status information
    hardware_status = {
        'camera': camera_processor.get_camera_status() if 'camera_processor' in globals() else {'available': False, 'error': 'Camera processor not initialized'},
        'controller': {'connected': ps4_controller.device is not None if 'ps4_controller' in globals() else False},
        'trilobot': {'available': hasattr(control_manager, 'robot') and control_manager.robot is not None if 'control_manager' in globals() else False},
    }
    
    # Pass status information to the template
    return render_template('index.html', 
                         stream_url=f'/stream.mjpg',
                         hardware_status=hardware_status)

def knight_rider_effect():
    """Knight Rider light effect"""
    log_info("Starting Knight Rider effect")
    
    # *** Use the shared robot instance ***
    tbot = control_manager.robot 
    if tbot is None or not hardware_available:
         log_warning("Knight Rider effect skipped: Hardware not available or not initialized.")
         return
    
    try:
        # We don't need to import Trilobot or constants here anymore
        # Assume constants were imported globally or use direct numbers if necessary
        lights = [
            LIGHT_FRONT_LEFT, LIGHT_MIDDLE_LEFT, LIGHT_REAR_LEFT,
            LIGHT_REAR_RIGHT, LIGHT_MIDDLE_RIGHT, LIGHT_FRONT_RIGHT
        ]
        
        interval = config.get("leds", "knight_rider_interval")
        
        while not stop_light_shows.is_set() and control_manager.knight_rider_active:
            # Forward
            for i in range(len(lights)):
                if stop_light_shows.is_set() or not control_manager.knight_rider_active:
                    break
                tbot.clear_underlighting(show=False)
                tbot.set_underlight(lights[i], (255, 0, 0), show=True)
                time.sleep(interval)
            # Backward
            for i in range(len(lights)-2, 0, -1):
                if stop_light_shows.is_set() or not control_manager.knight_rider_active:
                    break
                tbot.clear_underlighting(show=False)
                tbot.set_underlight(lights[i], (255, 0, 0), show=True)
                time.sleep(interval)
    except AttributeError as ae:
         log_error(f"Knight Rider effect error (likely missing method on robot instance): {ae}")
    except Exception as e:
        log_error(f"Knight Rider effect error: {e}")

def party_mode_effect():
    """Party mode light effect"""
    log_info("Starting Party mode effect")
    
    # *** Use the shared robot instance ***
    tbot = control_manager.robot
    if tbot is None or not hardware_available:
        log_warning("Party mode effect skipped: Hardware not available or not initialized.")
        return
    
    try:
        # We don't need to import Trilobot here anymore
        colors = [
            (255, 0, 0),    # Red
            (0, 255, 0),    # Green
            (0, 0, 255),    # Blue
            (255, 255, 0),  # Yellow
            (255, 0, 255),  # Magenta
            (0, 255, 255),  # Cyan
        ]
        
        interval = config.get("leds", "party_mode_interval")
        
        while not stop_light_shows.is_set() and control_manager.party_mode_active:
            for color in colors:
                if stop_light_shows.is_set() or not control_manager.party_mode_active:
                    break
                tbot.fill_underlighting(color)
                time.sleep(interval)
    except AttributeError as ae:
         log_error(f"Party mode effect error (likely missing method on robot instance): {ae}")
    except Exception as e:
        log_error(f"Party mode effect error: {e}")

def start_light_show(effect_function):
    """Start a light show in a separate thread"""
    global light_show_thread
    stop_light_shows.clear()
    
    if light_show_thread and light_show_thread.is_alive():
        stop_light_shows.set()
        light_show_thread.join()
    
    light_show_thread = threading.Thread(target=effect_function)
    light_show_thread.daemon = True
    light_show_thread.start()

@app.route('/button/<button_name>/<action>')
def handle_button(button_name, action):
    """Handle button presses from web interface"""
    print(f"DEBUG: handle_button entered with: button={button_name}, action={action}") 
    log_info(f"Button press received: {button_name} - {action} (Web)")
    
    try:
        is_active = (action == 'press')
        # *** Get the shared robot instance ***
        tbot = control_manager.robot 
        can_access_hw = hardware_available and tbot is not None
        
        if button_name == 'triangle':
            if is_active:
                # Toggle button LEDs
                control_manager.button_leds_active = not control_manager.button_leds_active
                
                # This assumes hardware access - guard it
                try:
                    # *** Use shared tbot instance ***
                    if can_access_hw:
                        for led in range(NUM_BUTTONS):
                            tbot.set_button_led(led, control_manager.button_leds_active)
                    else:
                         log_warning("Cannot set button LEDs: Hardware not available or not initialized.")
                except AttributeError as ae:
                     log_warning(f"Unable to set button LEDs (likely missing method on robot instance): {ae}")
                except Exception as e:
                    log_warning(f"Unable to access hardware LEDs: {e}")
        elif button_name == 'circle':
            if is_active:
                control_manager.execute_action(ControlAction.TOGGLE_KNIGHT_RIDER, source="web")
                if control_manager.knight_rider_active:
                    start_light_show(knight_rider_effect)
                else: # Ensure it stops if toggled off
                     stop_light_shows.set()
                     if can_access_hw:
                          try: tbot.clear_underlighting() 
                          except: pass # Ignore errors during clear
        elif button_name == 'cross':
            # *** Re-purposed: Take Photo ***
            if is_active:
                log_info("Web button Cross pressed -> TAKE_PHOTO") # Log change
                # Trigger take photo action
                control_manager.execute_action(ControlAction.TAKE_PHOTO, source="web")
                # Optional: Update status or provide feedback
                # document.getElementById('status-text').textContent = 'Taking photo...'; // Handled client-side ideally
        elif button_name == 'square':
            if is_active:
                control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE, source="web")
                if control_manager.party_mode_active:
                    start_light_show(party_mode_effect)
                else: # Ensure it stops if toggled off
                     stop_light_shows.set()
                     if can_access_hw:
                          try: tbot.clear_underlighting() 
                          except: pass # Ignore errors during clear
        
        return jsonify({
            'status': 'success',
            'button': button_name,
            'action': action,
            'states': {
                'button_leds': control_manager.button_leds_active,
                'knight_rider': control_manager.knight_rider_active,
                'party_mode': control_manager.party_mode_active
            }
        })
        
    except Exception as e:
        log_error(f"Button error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/move/<direction>/<action>')
def move(direction, action):
    """Handle movement commands from web interface"""
    log_info(f"Movement command received: {direction} - {action} (Web)")
    
    try:
        if action == 'start':
            if direction == 'forward':
                control_manager.execute_action(ControlAction.MOVE_FORWARD, source="web")
            elif direction == 'backward':
                control_manager.execute_action(ControlAction.MOVE_BACKWARD, source="web")
            elif direction == 'left':
                control_manager.execute_action(ControlAction.TURN_LEFT, source="web")
            elif direction == 'right':
                control_manager.execute_action(ControlAction.TURN_RIGHT, source="web")
        elif action == 'stop':
            control_manager.execute_action(ControlAction.STOP, source="web")
            
        return jsonify({
            'status': 'success',
            'direction': direction,
            'action': action
        })
        
    except Exception as e:
        log_error(f"Movement error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop')
def stop():
    """Stop all motors"""
    log_info(f"Emergency stop received (Web)")
    try:
        control_manager.execute_action(ControlAction.EMERGENCY_STOP, source="web")
        return jsonify({'status': 'success', 'message': 'Motors stopped'})
    except Exception as e:
        log_error(f"Stop error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stream.mjpg')
def stream():
    """Video streaming route."""
    def generate():
        """Generator function for video streaming."""
        from debugging import log_debug
        
        log_info("Starting camera stream generation.")
        stream_start_time = time.time()
        frame_count = 0
        last_log_time = stream_start_time
        
        output = camera_processor.get_stream()
        if output is None:
            log_error("Failed to get stream output from camera_processor.")
            # Potentially yield a static error image here
            return

        while True:
            try:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                
                if frame is None:
                    log_warning("Stream generator received None frame.")
                    time.sleep(0.1) # Avoid busy-waiting if frames stop
                    continue

                # Apply overlay - ensure this doesn't take too long
                # processed_frame = camera_processor.apply_overlay(frame)
                
                # Send the frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                frame_count += 1

                # Log frame count periodically
                current_time = time.time()
                if current_time - last_log_time >= 10.0: # Log every 10 seconds
                    fps = frame_count / (current_time - stream_start_time)
                    log_debug(f"Camera stream active: {frame_count} frames sent, ~{fps:.1f} FPS")
                    last_log_time = current_time

            except GeneratorExit:
                log_info("Camera stream generator stopped (client disconnected).")
                break
            except Exception as e:
                log_error(f"Error in camera stream generator: {e}")
                # Consider breaking or yielding an error frame
                time.sleep(1) # Pause before retrying after error
                # break # Uncomment to stop streaming on error
        
        log_info("Exiting camera stream generation loop.")

    # Return the response with the generator function
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- Mock Frame Generation (if hardware not available) ---
# Note: This part might need Pillow (PIL fork)
# sudo apt-get install python3-pil
def create_mock_frame():
    """Create a mock camera frame for testing without hardware."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        # Use a basic font if possible, otherwise skip text
        try:
            # Try common paths for default fonts
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if not os.path.exists(font_path):
                 font_path = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
            if not os.path.exists(font_path):
                font = ImageFont.load_default() # Fallback to PIL default
            else:
                 font = ImageFont.truetype(font_path, 20)
        except Exception:
             font = ImageFont.load_default()
        
        img = Image.new('RGB', (640, 480), color = (73, 109, 137)) # Blue-grey background
        d = ImageDraw.Draw(img)
        
        # Add timestamp and status text
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        status = "MOCK CAMERA - NO HARDWARE"
        d.text((10,10), timestamp, fill=(255,255,0), font=font)
        d.text((10,40), status, fill=(255,0,0), font=font)
        
        # Draw a simple pattern
        for i in range(0, 640, 20):
             d.line([(i, 0), (i, 480)], fill=(128, 128, 128))
        for i in range(0, 480, 20):
             d.line([(0, i), (640, i)], fill=(128, 128, 128))
             
        # Simulate movement state visually
        movement_state = state_tracker.get_state('movement')
        if movement_state == 'forward':
             d.polygon([(300, 200), (340, 200), (320, 180)], fill='green')
        elif movement_state == 'backward':
             d.polygon([(300, 260), (340, 260), (320, 280)], fill='red')
        elif movement_state == 'left':
             d.polygon([(280, 220), (300, 200), (300, 240)], fill='yellow')
        elif movement_state == 'right':
             d.polygon([(360, 220), (340, 200), (340, 240)], fill='yellow')
        else: # stopped
             d.rectangle([(310, 210), (330, 230)], fill='gray')

        # Convert to JPEG bytes
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        return buf.getvalue()
    except ImportError:
        # Fallback if Pillow is not installed
        log_warning("Pillow (PIL) not installed. Cannot generate mock frames.")
        # Return a minimal response or placeholder bytes
        return b'--frame\r\nContent-Type: text/plain\r\n\r\nMock frame error: Pillow not found.\r\n'
    except Exception as e:
        log_error(f"Error creating mock frame: {e}")
        return b'--frame\r\nContent-Type: text/plain\r\n\r\nMock frame generation error.\r\n'
# --- End Mock Frame Generation ---

def cleanup():
    """Clean up resources, especially light shows"""
    log_info("Stopping web control background tasks...")
    stop_light_shows.set()
    if light_show_thread and light_show_thread.is_alive():
        light_show_thread.join(timeout=1.0)

@app.route('/test')
def test():
    """Test if the web server is running"""
    return "Web control server is running!"

@app.route('/camera_status')
def camera_status():
    """Get the status of the camera"""
    try:
        status = camera_processor.get_camera_status()
        # Add Trilobot hardware status
        status['trilobot_available'] = hasattr(control_manager, 'robot') and not isinstance(control_manager.robot, MockTrilobot)
        # Add PS4 controller status
        status['ps4_controller'] = ps4_controller.device is not None if hasattr(ps4_controller, 'device') else False
        return jsonify(status)
    except Exception as e:
        log_error(f"Error getting camera status: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

def main():
    """Main function to start the web control server"""
    try:
        log_info("Starting initialization...")
        
        # Start control manager
        control_manager.start()
        
        # Initialize and start camera processor
        camera_processor.start()
            
        # Start Flask server
        web_port = config.get("web_server", "port")
        web_host = config.get("web_server", "host")
        debug_mode = config.get("web_server", "debug")
        
        log_info(f"Starting web interface on {web_host}:{web_port}")
        app.run(host=web_host, port=web_port, threaded=True, debug=debug_mode)
        
    except Exception as e:
        log_error(f"Web control startup error: {e}")
        raise
    finally:
        cleanup()

if __name__ == '__main__':
    main()