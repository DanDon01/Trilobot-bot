"""
Drop-in replacement for camera_processor when picamera2 is unavailable.
Uses OpenCV + V4L2 to grab frames from /dev/video0.
"""

import cv2
import threading
import time
from threading import Condition
import logging

logger = logging.getLogger('trilobot.camera_cv')

class StreamingOutput:
    def __init__(self):
        self.frame = None
        self.condition = Condition()

class CameraCV:
    def __init__(self, cam_index=0, width=640, height=480):
        self.cam_index = cam_index
        self.width = width
        self.height = height
        self.cap = None
        self.thread = None
        self.running = False
        self.output = StreamingOutput()

    def _capture_loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                continue
            # Encode to JPEG in-memory
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            with self.output.condition:
                self.output.frame = jpeg.tobytes()
                self.output.condition.notify_all()

    def start(self):
        logger.info("Starting OpenCV camera backend")
        self.cap = cv2.VideoCapture(self.cam_index)
        if not self.cap.isOpened():
            raise RuntimeError("Unable to open /dev/video{}".format(self.cam_index))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()

    # shim so web_control can call same names
    def get_stream(self):
        return self.output

    def get_camera_status(self):
        return {"available": True, "running": self.running, "error": None}

# create global
camera_processor = CameraCV()
