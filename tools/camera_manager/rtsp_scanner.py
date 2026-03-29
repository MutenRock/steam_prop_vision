# -*- coding: utf-8 -*-
"""
Scan caméras locales et test de sources RTSP.
Version silencieuse — supprime les warnings OpenCV/V4L2 sur stderr.
"""
from __future__ import annotations
import os
import sys
import platform
from typing import List, Tuple

try:
    import cv2
except ImportError:
    cv2 = None


def _silence_opencv():
    """Redirige stderr pour supprimer les warnings V4L2/FFMPEG pendant le scan."""
    import contextlib
    # Désactive les logs OpenCV
    if cv2 is not None:
        cv2.setLogLevel(0)  # 0 = SILENT


def scan_local_cameras(max_index: int = 6) -> List[Tuple[int, int, int]]:
    """
    Retourne [(index, width, height)] pour chaque caméra locale détectée.
    Silencieux — ne spamme pas les warnings V4L2 si aucune cam n'est branchée.
    """
    if cv2 is None:
        return []

    _silence_opencv()

    # Redirige stderr OS-level pendant le scan pour éviter les warnings V4L2
    devnull = open(os.devnull, "w")
    old_stderr_fd = os.dup(2)
    os.dup2(devnull.fileno(), 2)

    found = []
    try:
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_V4L2
        for i in range(max_index):
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                found.append((i, w, h))
            cap.release()
    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(old_stderr_fd)
        devnull.close()

    return found


def test_rtsp_source(source: str, timeout_s: float = 5.0) -> Tuple[bool, str]:
    """
    Tente d'ouvrir la source (index ou URL RTSP) et lit une frame.
    Retourne (success, message).
    """
    if cv2 is None:
        return False, "OpenCV non disponible"

    _silence_opencv()

    cap_source = int(source) if source.strip().isdigit() else source
    cap = cv2.VideoCapture(cap_source, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        cap.release()
        return False, f"Impossible d'ouvrir : {source}"

    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        return False, f"Source ouverte mais frame illisible : {source}"

    h, w = frame.shape[:2]
    return True, f"✅ OK — {w}x{h} — {source}"
