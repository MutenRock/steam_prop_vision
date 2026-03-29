# -*- coding: utf-8 -*-
"""
Supprime les warnings OpenCV (V4L2, FFMPEG) au démarrage de l'app.
Importer en tout premier dans main ou gui/app.py.

Usage :
    import core.suppress_cv_warnings  # noqa — doit être en premier
"""
import os

# Désactive les logs OpenCV avant tout import cv2
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")

try:
    import cv2
    cv2.setLogLevel(0)  # 0 = cv::utils::logging::LOG_LEVEL_SILENT
except Exception:
    pass
