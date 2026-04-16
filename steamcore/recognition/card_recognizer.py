"""
steamcore/recognition/card_recognizer.py

Logique de reconnaissance :
  - Chaque plaque peut avoir N images dans son dossier PLATEST (ex: bougie.jpg,
    bougie_top.jpg, bougie_bottom.jpg, bougie_left.jpg, bougie_right.jpg).
  - Pour chaque image template, on tente un match ORB global.
  - Si AU MOINS UNE image template matche (score >= threshold ET matches >= min_matches)
    → la plaque est validée.
  - Le score final retourné est le meilleur score parmi toutes les images.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import cv2
import numpy as np


def _find_images(directory: Path) -> list:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.rglob(ext))
    return sorted(p for p in imgs if not p.name.startswith("."))


@dataclass
class RecognitionResult:
    card_id:      str
    label:        str
    score:        float
    matches:      int
    matched_img:  str = ""   # nom de l'image qui a matché


class CardRecognizer:
    WARP_SIZE  = 400
    RATIO_TEST = 0.75

    def __init__(
        self,
        platest_dir:  str   = "PLATEST",
        min_matches:  int   = 6,
        threshold:    float = 0.03,
    ):
        self.platest_dir = platest_dir
        self.min_matches = min_matches
        self.threshold   = threshold
        self._orb     = cv2.ORB_create(nfeatures=800)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._templates: list = []
        self._load()

    def load_config(self, cfg: dict):
        det = cfg.get("detection", {})
        self.min_matches = det.get("min_matches", self.min_matches)
        self.threshold   = det.get("threshold",   self.threshold)
        self.reload()

    def recognize(self, warped: np.ndarray, hint_id: str | None = None):
        gray = self._to_gray(warped)
        gray = cv2.resize(gray, (self.WARP_SIZE, self.WARP_SIZE))

        kps_q, desc_q = self._orb.detectAndCompute(gray, None)
        if desc_q is None:
            return None

        templates = self._templates
        if hint_id:
            templates = [t for t in self._templates if t.card_id == hint_id] or self._templates

        best_score, best_matches, best_id, best_img = 0.0, 0, None, ""

        for tmpl in templates:
            # Tente chaque image du template — valide si UNE seule matche
            for img_name, kps_r, desc_r in tmpl.images:
                try:
                    ms   = self._matcher.knnMatch(desc_q, desc_r, k=2)
                    good = [m for m, n in ms
                            if m.distance < self.RATIO_TEST * n.distance]
                    score = len(good) / max(len(kps_r), len(kps_q), 1)
                    if score >= self.threshold and len(good) >= self.min_matches:
                        if score > best_score:
                            best_score   = score
                            best_matches = len(good)
                            best_id      = tmpl.card_id
                            best_img     = img_name
                except Exception:
                    continue

        if best_id is None:
            return None

        label = best_id.replace("plate_", "").replace("_", " ").capitalize()
        return RecognitionResult(
            card_id=best_id, label=label,
            score=round(best_score, 4),
            matches=best_matches,
            matched_img=best_img,
        )

    def reload(self):
        self._templates.clear()
        self._load()

    @property
    def card_ids(self) -> list:
        return [t.card_id for t in self._templates]

    def _load(self):
        p = Path(self.platest_dir)
        if not p.exists():
            print("[recognizer] PLATEST introuvable : " + str(p))
            return
        for subdir in sorted(p.iterdir()):
            if not subdir.is_dir():
                continue
            imgs = _find_images(subdir)
            if not imgs:
                continue
            tmpl = _OrbTemplate(subdir.name, imgs, self._orb)
            if tmpl.images:
                self._templates.append(tmpl)
                print(f"[recognizer] {subdir.name} ({len(tmpl.images)} imgs)")
        print(f"[recognizer] {len(self._templates)} cartes chargees")

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        return img if len(img.shape) == 2 \
            else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


class _OrbTemplate:
    """Charge toutes les images d'une plaque et stocke leurs descripteurs ORB."""
    def __init__(self, card_id: str, paths, orb):
        self.card_id = card_id
        self.images: list = []   # [(nom_fichier, kps, desc), ...]
        S = CardRecognizer.WARP_SIZE
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (S, S))
            kps, desc = orb.detectAndCompute(gray, None)
            if desc is not None and len(kps) >= 4:
                self.images.append((p.name, kps, desc))
