from picamera2 import Picamera2
from flask import Flask, Response
import cv2
import threading

app = Flask(__name__)
cam = Picamera2()
cam.configure(cam.create_preview_configuration(
    main={"size": (1280, 720), "format": "RGB888"}
))
cam.start()

lock = threading.Lock()

def gen_frames():
    while True:
        frame = cam.capture_array()
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return '<img src="/stream" style="width:100%">'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, threaded=True)
