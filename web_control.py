from flask import Flask, render_template, jsonify
from trilobot import Trilobot
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import cv2
import numpy as np
from datetime import datetime
import io
import time
import threading
import os
from threading import Condition
import socketserver
from http import server

app = Flask(__name__)
tbot = Trilobot()

# Global variables
SPEED = 1.0
ACCELERATION = 0.5
current_speeds = {'left': 0, 'right': 0}
camera = None
output = None
overlay_mode = 'normal'

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()
        
    def write(self, buf):
        try:
            # Convert buffer to numpy array
            nparr = np.frombuffer(buf, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return
            
            # Simple overlays based on mode
            if overlay_mode == 'normal':
                # Add timestamp only
                cv2.putText(frame, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                          (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
            elif overlay_mode == 'night_vision':
                # Simple green tint
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = cv2.applyColorMap(frame, cv2.COLORMAP_BONE)
                
            elif overlay_mode == 'targeting':
                # Simple crosshair
                h, w = frame.shape[:2]
                cv2.line(frame, (w//2, h//2 - 20), (w//2, h//2 + 20), (0, 0, 255), 2)
                cv2.line(frame, (w//2 - 20, h//2), (w//2 + 20, h//2), (0, 0, 255), 2)
            
            # Encode frame
            _, encoded_frame = cv2.imencode('.jpg', frame)
            with self.condition:
                self.frame = encoded_frame.tobytes()
                self.condition.notify_all()
                
        except Exception as e:
            print(f"Frame processing error: {e}")

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                print(f"Streaming error: {e}")
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def init_camera():
    global camera, output
    try:
        # Kill any existing camera processes
        os.system('sudo fuser -k /dev/video0 2>/dev/null')
        time.sleep(1)
        
        camera = Picamera2()
        camera.configure(camera.create_video_configuration(main={"size": (640, 480)}))
        output = StreamingOutput()
        encoder = MJPEGEncoder(bitrate=1000000)
        camera.start_recording(encoder, FileOutput(output))
        print("Camera initialized successfully")
        return True
    except Exception as e:
        print(f"Camera initialization error: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/overlay/<mode>')
def set_overlay(mode):
    global overlay_mode
    try:
        overlay_mode = mode
        print(f"Overlay mode set to: {mode}")
        return jsonify({'status': 'success', 'mode': mode})
    except Exception as e:
        print(f"Overlay error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

def cleanup():
    global camera
    if camera:
        try:
            camera.stop_recording()
            camera.close()
        except:
            pass
    tbot.disable_motors()

if __name__ == '__main__':
    try:
        # Initialize camera
        if init_camera():
            # Start camera server
            camera_server = StreamingServer(('', 8000), StreamingHandler)
            server_thread = threading.Thread(target=camera_server.serve_forever)
            server_thread.daemon = True
            server_thread.start()
        
        # Start Flask app
        app.run(host='0.0.0.0', port=5000, debug=False)  # Set debug to False
    except Exception as e:
        print(f"Startup error: {e}")
    finally:
        cleanup()