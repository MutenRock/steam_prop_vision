"""
steamcore/recognition/pipeline.py
Orchestrateur 2 niveaux avec ROI dynamique.

Niveau 1 (thread principal) : FastDetector -> quad rapide + ROI
Niveau 2 (thread background): CardDetector + CardRecognizer sur ROI

Usage:
    pipe = RecognitionPipeline(platest_dir="PLATEST")
    pipe.start()
    ...
    result = pipe.process_frame(frame)  # non-bloquant
    if result:
        print(result.card_id, result.score)
    ...
    pipe.stop()
"""
from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from queue import Queue, Empty

import cv2
import numpy as np

from .fast_detector   import FastDetector, QuadROI
from .card_detector   import CardDetector
from .card_recognizer import CardRecognizer, RecognitionResult


@dataclass
class PipelineResult:
    card_id:    str
    label:      str
    score:      float
    matches:    int
    roi:        QuadROI
    timestamp:  float


class RecognitionPipeline:
    """
    Orchestrateur 2 niveaux non-bloquant.
    process_frame() est appele sur le thread principal (rapide).
    La reconnaissance lourde tourne en background.
    """

    def __init__(
        self,
        platest_dir:    str   = "PLATEST",
        backend:        str   = "orb",     # "orb" ou "sift"
        min_matches_l2: int   = 8,
        min_inliers:    int   = 6,
        ratio_test:     float = 0.75,
        orb_threshold:  float = 0.04,
        bg_interval:    float = 0.4,       # s entre deux analyses background
        result_ttl:     float = 3.0,       # s avant d'expirer un resultat
    ):
        self.bg_interval  = bg_interval
        self.result_ttl   = result_ttl

        self._fast      = FastDetector()
        self._detector  = CardDetector(
            platest_dir=platest_dir,
            backend=backend,
            min_matches=min_matches_l2,
            min_inliers=min_inliers,
            ratio_test=ratio_test,
        )
        self._recognizer = CardRecognizer(
            platest_dir=platest_dir,
            threshold=orb_threshold,
        )

        self._queue:  Queue       = Queue(maxsize=2)
        self._result: PipelineResult | None = None
        self._result_lock         = threading.Lock()
        self._running             = False
        self._thread: threading.Thread | None = None

    def load_config(self, cfg: dict):
        self._fast.load_config(cfg)
        self._detector.load_config(cfg)
        self._recognizer.load_config(cfg)
        pipe_cfg = cfg.get("pipeline", {})
        self.bg_interval = pipe_cfg.get("bg_interval", self.bg_interval)
        self.result_ttl  = pipe_cfg.get("result_ttl",  self.result_ttl)

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._bg_loop, daemon=True, name="recognition-bg"
        )
        self._thread.start()
        print("[pipeline] background thread started (backend=" +
              self._detector.backend + ")")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def process_frame(self, frame: np.ndarray) -> PipelineResult | None:
        """
        Appele sur le thread principal.
        1. Detecte un quad (rapide).
        2. Si quad trouve, envoie la ROI au thread background (non-bloquant).
        3. Retourne le dernier resultat confirme (ou None si expire).
        """
        quad = self._fast.detect(frame)
        if quad is not None:
            roi = quad.crop(frame)
            try:
                self._queue.put_nowait((roi, quad))
            except Exception:
                pass   # queue pleine, on skip ce frame

        with self._result_lock:
            r = self._result
            if r is not None and (time.time() - r.timestamp) > self.result_ttl:
                self._result = None
                r = None
            return r

    @property
    def last_result(self) -> PipelineResult | None:
        with self._result_lock:
            return self._result

    @property
    def card_ids(self) -> list:
        return self._detector.card_ids

    def reload(self):
        self._detector.reload()
        self._recognizer.reload()

    def draw_overlay(self, frame: np.ndarray,
                     quad: QuadROI | None = None) -> np.ndarray:
        """Dessine les overlays OSD sur la frame (pour debug/stream)."""
        out = frame.copy()
        if quad is not None:
            pts = quad.corners.astype(int)
            for i in range(4):
                cv2.line(out, tuple(pts[i]), tuple(pts[(i+1) % 4]),
                         (0, 255, 100), 2)
            cv2.rectangle(out, (quad.x, quad.y),
                          (quad.x + quad.w, quad.y + quad.h),
                          (0, 180, 255), 1)
        with self._result_lock:
            r = self._result
        if r is not None:
            txt = r.card_id + "  " + str(round(r.score, 3))
            cv2.putText(out, txt, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
            cv2.putText(out, txt, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
        return out

    # ── background thread ────────────────────────────────────────────────────

    def _bg_loop(self):
        last_run = 0.0
        while self._running:
            try:
                roi, quad = self._queue.get(timeout=0.5)
            except Empty:
                continue

            now = time.time()
            if (now - last_run) < self.bg_interval:
                continue   # throttle
            last_run = now

            try:
                region = self._detector.detect(roi)
                if region is None:
                    continue
                result = self._recognizer.recognize(
                    region.warped,
                    hint_id=region.card_id,
                )
                if result is None:
                    continue
                pr = PipelineResult(
                    card_id=result.card_id,
                    label=result.label,
                    score=result.score,
                    matches=result.matches,
                    roi=quad,
                    timestamp=time.time(),
                )
                with self._result_lock:
                    self._result = pr
                print("[pipeline] CONFIRMED " + result.card_id +
                      " score=" + str(round(result.score, 3)))
            except Exception as e:
                print("[pipeline] bg error : " + str(e))
