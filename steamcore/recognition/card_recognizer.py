"""
steamcore/recognition/card_recognizer.py

Reconnaît quelle carte parmi les 5 illustrations est présentée.
Travaille sur une image DÉJÀ normalisée 400×400 (sortie de CardDetector).

Pipeline :
  - Charger les templates depuis PLATEST/plateXX/images/
  - Pour chaque template : précalculer les descripteurs ORB
  - Match frame normalisée vs templates → retourner la meilleure carte

Pourquoi ça marche maintenant :
  - Image normalisée = même taille, même orientation approximative
  - Illustrations B&W = densité max de keypoints ORB
  - 5 scènes très distinctes = confusion inter-cartes quasi impossible
"""
from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
import yaml

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WARP_SIZE = 400


@dataclass
class CardTemplate:
    id: str
    label: str
    info: dict
    descriptors: list[tuple]   # (kps, desc, img_name) par image de référence
    image_count: int = 0


@dataclass
class RecognitionResult:
    card_id: str
    label: str
    score: float        # ratio de bons matches (0→1)
    match_count: int
    trigger_action: str
    info: dict


class CardRecognizer:
    def __init__(
        self,
        platest_dir: str = "PLATEST",
        min_good_matches: int = 12,
        ratio_thresh: float = 0.75,
        score_threshold: float = 0.08,  # ~12 good matches sur ~150 kps
    ):
        self.platest_dir    = Path(platest_dir)
        self.min_good_matches = min_good_matches
        self.ratio_thresh   = ratio_thresh
        self.score_threshold = score_threshold

        self._orb     = cv2.ORB_create(nfeatures=800)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._templates: list[CardTemplate] = []

        self.reload()

    # ── Chargement ────────────────────────────────────────────────
    def reload(self) -> None:
        self._templates.clear()
        if not self.platest_dir.exists():
            print(f"[recognizer] PLATEST introuvable : {self.platest_dir}")
            return
        for d in sorted(self.platest_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            t = self._load_template(d)
            if t:
                self._templates.append(t)
        print(f"[recognizer] {len(self._templates)} cartes chargées")

    def _load_template(self, plate_dir: Path) -> CardTemplate | None:
        info = {}
        info_path = plate_dir / "info.yaml"
        if info_path.exists():
            with open(info_path, encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}

        card_id = info.get("id", plate_dir.name)
        label   = info.get("label", plate_dir.name)
        img_dir = plate_dir / "images"
        descs   = []

        if img_dir.exists():
            for img_path in sorted(img_dir.iterdir()):
                if img_path.suffix.lower() not in IMG_EXT:
                    continue
                img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                # Normaliser à WARP_SIZE comme la détection
                img = cv2.resize(img, (WARP_SIZE, WARP_SIZE))
                # CLAHE sur le template aussi pour cohérence
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                img   = clahe.apply(img)
                kps, desc = self._orb.detectAndCompute(img, None)
                if desc is not None and len(kps) >= 8:
                    descs.append((kps, desc, img_path.name))

        if not descs:
            print(f"[recognizer] ! {card_id} : aucune image de référence valide")
            return None

        print(f"[recognizer]   + {card_id} ({len(descs)} imgs, {label})")
        return CardTemplate(
            id=card_id, label=label, info=info,
            descriptors=descs, image_count=len(descs)
        )

    # ── Reconnaissance ────────────────────────────────────────────
    def recognize(self, warped_frame: np.ndarray) -> RecognitionResult | None:
        """
        warped_frame : image 400×400 sortie de CardDetector.warp()
        Retourne la carte reconnue ou None.
        """
        # Préparer query
        gray = cv2.cvtColor(warped_frame, cv2.COLOR_BGR2GRAY)                if len(warped_frame.shape) == 3 else warped_frame
        gray = cv2.resize(gray, (WARP_SIZE, WARP_SIZE))
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray  = clahe.apply(gray)

        kps_q, desc_q = self._orb.detectAndCompute(gray, None)
        if desc_q is None or len(kps_q) < 8:
            return None

        best: RecognitionResult | None = None

        for template in self._templates:
            score, count = self._match_template(desc_q, kps_q, template)
            if count < self.min_good_matches:
                continue
            if score < self.score_threshold:
                continue
            action = template.info.get(
                "trigger_action", f"STEAM_DETECT_{template.id.upper()}"
            )
            result = RecognitionResult(
                card_id=template.id, label=template.label,
                score=score, match_count=count,
                trigger_action=action, info=template.info
            )
            if best is None or result.score > best.score:
                best = result

        return best

    def _match_template(
        self, desc_q: np.ndarray, kps_q, template: CardTemplate
    ) -> tuple[float, int]:
        best_score = 0.0
        best_count = 0
        for kps_ref, desc_ref, _ in template.descriptors:
            matches = self._matcher.knnMatch(desc_q, desc_ref, k=2)
            good = [m for m, n in matches if m.distance < self.ratio_thresh * n.distance]
            score = len(good) / max(len(kps_ref), len(kps_q), 1)
            if score > best_score:
                best_score = score
                best_count = len(good)
        return best_score, best_count

    # ── Infos ─────────────────────────────────────────────────────
    def list_cards(self) -> list[dict]:
        return [{"id": t.id, "label": t.label, "images": t.image_count}
                for t in self._templates]

    def summary(self) -> str:
        return f"recognizer: {len(self._templates)} cartes ORB"
