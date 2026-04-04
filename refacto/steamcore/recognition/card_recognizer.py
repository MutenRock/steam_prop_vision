from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
import yaml

IMG_EXT   = {".jpg",".jpeg",".png",".bmp",".webp"}
WARP_SIZE = 400

@dataclass
class RecognitionResult:
    card_id: str
    label:   str
    score:   float
    matches: int
    action:  str

@dataclass
class _Template:
    id:    str
    label: str
    action: str
    descs: list = field(default_factory=list)  # [(kps, desc)]

class CardRecognizer:
    def __init__(self, platest_dir="PLATEST", min_matches=12,
                 ratio=0.75, threshold=0.08):
        self.platest_dir = Path(platest_dir)
        self.min_matches = min_matches
        self.ratio       = ratio
        self.threshold   = threshold
        self._orb        = cv2.ORB_create(nfeatures=800)
        self._matcher    = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._templates  = []
        self.reload()

    def reload(self):
        self._templates.clear()
        if not self.platest_dir.exists():
            print(f"[recognizer] PLATEST introuvable : {self.platest_dir}")
            return
        for d in sorted(self.platest_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."): continue
            info = {}
            if (d/"info.yaml").exists():
                info = yaml.safe_load((d/"info.yaml").read_text()) or {}
            t = _Template(
                id     = info.get("id", d.name),
                label  = info.get("label", d.name),
                action = info.get("trigger_action", f"STEAM_{d.name.upper()}"),
            )
            img_dir = d / "images"
            if img_dir.exists():
                for p in sorted(img_dir.iterdir()):
                    if p.suffix.lower() not in IMG_EXT: continue
                    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                    if img is None: continue
                    img = cv2.resize(img, (WARP_SIZE, WARP_SIZE))
                    kps, desc = self._orb.detectAndCompute(img, None)
                    if desc is not None and len(kps) >= 8:
                        t.descs.append((kps, desc))
            if t.descs:
                self._templates.append(t)
                print(f"[recognizer] + {t.id} ({len(t.descs)} imgs)")
        print(f"[recognizer] {len(self._templates)} cartes chargées")

    def recognize(self, warped: np.ndarray) -> RecognitionResult | None:
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY) if len(warped.shape)==3 else warped
        gray = cv2.resize(gray, (WARP_SIZE, WARP_SIZE))
        kps_q, desc_q = self._orb.detectAndCompute(gray, None)
        if desc_q is None or len(kps_q) < 8: return None

        best = None
        for t in self._templates:
            top_score, top_count = 0.0, 0
            for kps_r, desc_r in t.descs:
                matches = self._matcher.knnMatch(desc_q, desc_r, k=2)
                good    = [m for m,n in matches if m.distance < self.ratio*n.distance]
                score   = len(good) / max(len(kps_r), len(kps_q), 1)
                if score > top_score:
                    top_score, top_count = score, len(good)
            if top_count >= self.min_matches and top_score >= self.threshold:
                if best is None or top_score > best.score:
                    best = RecognitionResult(t.id, t.label, top_score, top_count, t.action)
        return best

    def summary(self): return f"recognizer: {len(self._templates)} cartes ORB"
