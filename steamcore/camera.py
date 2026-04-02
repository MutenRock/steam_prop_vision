"""
steamcore/camera.py
Auto-détecte Picamera2 (Pi 5) ou OpenCV (desktop).
Config validée par BigEye : imgsz=320, ~15 FPS pipeline réel.
"""
from __future__ import annotations
import platform
import time
import numpy as np


def is_rpi() -> bool:
    return platform.machine() in ("aarch64", "armv7l")


class Camera:
    def __init__(self, resolution=(1280, 720)):
        self._resolution = resolution
        self._cam = None
        self._backend = None

    def start(self):
        if is_rpi():
            from picamera2 import Picamera2
            self._cam = Picamera2()
            self._cam.configure(
                self._cam.create_preview_configuration(
                    main={"size": self._resolution, "format": "RGB888"}
                )
            )
            self._cam.start()
            time.sleep(1.0)  # AWB warmup IMX708
            self._backend = "picamera2"
        else:
            import cv2
            api = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_V4L2
            self._cam = cv2.VideoCapture(0, api)
            self._backend = "opencv"

    def read(self):
        """Retourne (ok, frame_BGR numpy)"""
        if self._backend == "picamera2":
            import cv2
            rgb = self._cam.capture_array()
            return True, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        else:
            return self._cam.read()

    def stop(self):
        if self._cam and self._backend == "picamera2":
            self._cam.stop()
        elif self._cam:
            self._cam.release()

    @property
    def backend(self):
        return self._backend
