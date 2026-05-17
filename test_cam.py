from picamera2 import Picamera2
import cv2

cam = Picamera2()
cam.configure(cam.create_preview_configuration(
    main={"size": (1280, 720), "format": "RGB888"}
))
cam.start()

while True:
    frame = cam.capture_array()
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imshow("steam_prop_vision", bgr)
    if cv2.waitKey(1) == ord('q'):
        break

cam.stop()
