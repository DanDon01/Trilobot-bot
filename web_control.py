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
from debugging import log_info, log_error, log_warning, state_tracker, log_debug, safe_log
from config import config
from control_manager import control_manager, ControlMode, ControlAction
from camera_processor import camera_processor
from voice_controller import voice_controller

logger = logging.getLogger('trilobot.web')

# Try to import hardware-specific modules
try:
    from trilobot import Trilobot
    # Try to get constants separately to avoid issues if some are missing
    try:
        from trilobot import NUM_BUTTONS, LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT, LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT, LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT
    except ImportError:
        # Define fallback constants if not available
        NUM_BUTTONS = 6
        LIGHT_FRONT_LEFT, LIGHT_FRONT_RIGHT = 0, 1
        LIGHT_MIDDLE_LEFT, LIGHT_MIDDLE_RIGHT = 2, 3
        LIGHT_REAR_LEFT, LIGHT_REAR_RIGHT = 4, 5
        log_warning("Trilobot constants not available, using fallback values.")
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

# Initialize Flask with explicit static folder path
current_dir = os.path.dirname(os.path.abspath(__file__))
static_folder = os.path.join(current_dir, 'static')
app = Flask(__name__, static_folder=static_folder)

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

# Global variables for voice activity tracking
last_voice_activity = ""
voice_activity_timestamp = 0

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
    from debugging import log_debug
    log_debug(f"Web button handler: {button_name} - {action}")
    print(f"DEBUG: handle_button entered with: button={button_name}, action={action}") 
    log_info(f"Button press received: {button_name} - {action} (Web)")
    
    try:
        is_active = (action == 'press')
        # *** Get the shared robot instance ***
        tbot = control_manager.robot 
        can_access_hw = hardware_available and tbot is not None
        log_debug(f"Web button hardware access: {can_access_hw}")
        
        if button_name == 'triangle':
            if is_active:
                # Toggle button LEDs
                log_debug(f"Web triangle button: toggling LEDs, current state: {control_manager.button_leds_active}")
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
                log_debug(f"Web circle button: toggling Knight Rider, current state: {control_manager.knight_rider_active}")
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
                log_debug(f"Web cross button: taking photo")
                log_info("Web button Cross pressed -> TAKE_PHOTO") # Log change
                # Trigger take photo action
                control_manager.execute_action(ControlAction.TAKE_PHOTO, source="web")
                # Optional: Update status or provide feedback
                # document.getElementById('status-text').textContent = 'Taking photo...'; // Handled client-side ideally
        elif button_name == 'square':
            if is_active:
                log_debug(f"Web square button: toggling Party Mode, current state: {control_manager.party_mode_active}")
                control_manager.execute_action(ControlAction.TOGGLE_PARTY_MODE, source="web")
                if control_manager.party_mode_active:
                    start_light_show(party_mode_effect)
                else: # Ensure it stops if toggled off
                     stop_light_shows.set()
                     if can_access_hw:
                          try: tbot.clear_underlighting() 
                          except: pass # Ignore errors during clear
        
        log_debug(f"Web button response: success for {button_name}")
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
        import traceback
        error_traceback = traceback.format_exc()
        log_debug(f"Web button error traceback: {error_traceback}")
        print(f"BUTTON ERROR (Web): {e}\n{error_traceback}")
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
        from debugging import safe_log  # Use our safer logging function
        
        # Reduce log frequency - only log once at the start
        try:
            safe_log(logger, 'info', "Starting camera stream generation.")
        except Exception:
            pass  # Ignore logging errors
            
        stream_start_time = time.time()
        frame_count = 0
        last_log_time = stream_start_time
        
        # Get the absolute path to no-camera.png
        no_camera_path = os.path.join(current_dir, 'static', 'no-camera.png')
        
        # Check if the file exists - silently handle this
        if not os.path.exists(no_camera_path):
            # Use a simpler approach if file doesn't exist
            fallback_img = b''
        else:
            # Load the fallback image once
            try:
                with open(no_camera_path, 'rb') as f:
                    fallback_img = f.read()
            except Exception:
                fallback_img = b''
        
        output = camera_processor.get_stream()
        if output is None:
            # Return an error frame rather than None
            yield (b'--frame\r\n'
                  b'Content-Type: image/jpeg\r\n\r\n' + fallback_img + b'\r\n')
            return

        while True:
            try:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                
                if frame is None:
                    # Yield the placeholder image when frame is None
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + fallback_img + b'\r\n')
                    time.sleep(0.1) # Avoid busy-waiting if frames stop
                    continue

                # Send the frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                frame_count += 1

                # Log frame count periodically - but less frequently
                current_time = time.time()
                if current_time - last_log_time >= 60.0: # Log only every 60 seconds
                    fps = frame_count / (current_time - stream_start_time)
                    try:
                        safe_log(logger, 'debug', f"Camera stream active: {frame_count} frames sent, ~{fps:.1f} FPS")
                    except Exception:
                        pass  # Ignore logging errors
                    last_log_time = current_time

            except GeneratorExit:
                try:
                    safe_log(logger, 'info', "Camera stream generator stopped (client disconnected).")
                except Exception:
                    pass  # Ignore logging errors
                break
            except Exception as e:
                try:
                    safe_log(logger, 'error', f"Error in camera stream generator: {e}")
                except Exception:
                    pass  # Ignore logging errors
                    
                # Yield the error image on exceptions
                try:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + fallback_img + b'\r\n')
                except:
                    pass  # Ignore errors during error handling
                time.sleep(1) # Pause before retrying after error
        
        # Final message - try to log but don't worry if it fails
        try:
            safe_log(logger, 'info', "Exiting camera stream generation loop.")
        except Exception:
            pass

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

@app.route('/system_status')
def system_status():
    """Return system status as JSON for the web UI"""
    try:
        # Import here to avoid circular imports
        from ps4_controller import ps4_controller

        # Get camera status
        camera_status = camera_processor.get_camera_status()
        
        # Get voice status
        voice_status = {
            "enabled": voice_controller.enabled,
            "microphone": voice_controller.microphone is not None,
            "recognizer": voice_controller.recognizer is not None,
            "audio": voice_controller.audio_available,
            "running": voice_controller.recognition_thread is not None and voice_controller.recognition_thread.is_alive(),
        }
        
        # Get controller status
        controller_status = {
            "connected": hasattr(ps4_controller, 'device') and ps4_controller.device is not None,
            "running": ps4_controller.running,
        }
        
        # Get robot status from state tracker
        robot_status = {
            "control_mode": state_tracker.get_state("control_mode"),
            "movement_state": state_tracker.get_state("movement"),
            "led_mode": state_tracker.get_state("led_mode"),
        }
        
        return jsonify({
            "camera": camera_status,
            "voice": voice_status,
            "controller": controller_status,
            "movement_state": robot_status["movement_state"],
            "control_mode": robot_status["control_mode"],
            "led_mode": robot_status["led_mode"],
        })
    except Exception as e:
        log_error(f"Error getting system status: {e}")
        return jsonify({"error": str(e)})

@app.route('/voice_activity')
def voice_activity():
    """Return the latest voice activity as JSON for the web UI"""
    global last_voice_activity, voice_activity_timestamp
    
    # Only return activity if it's recent (last 30 seconds)
    current_time = time.time()
    if current_time - voice_activity_timestamp > 30:
        last_voice_activity = "" 
    
    return jsonify({
        "activity": last_voice_activity,
        "timestamp": voice_activity_timestamp
    })

# Function to record voice activity
def record_voice_activity(activity):
    """Record voice activity for the web UI to display"""
    global last_voice_activity, voice_activity_timestamp
    last_voice_activity = activity
    voice_activity_timestamp = time.time()
    log_debug(f"Voice activity recorded: {activity}")

@app.route('/ping')
def ping():
    """Simple endpoint to check if the server is responding"""
    return jsonify({
        'status': 'success',
        'message': 'Trilobot web server is operational',
        'timestamp': time.time()
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