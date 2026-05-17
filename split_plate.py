"""
split_plate.py
Usage : python3 split_plate.py <image> [--platest PLATEST] [--overlap 0.15]

Génère 4 crops avec overlap depuis une image de plaque :
  - top_half    : moitié haute  (+ overlap bas)
  - bottom_half : moitié basse  (+ overlap haut)
  - left_half   : moitié gauche (+ overlap droite)
  - right_half  : moitié droite (+ overlap gauche)

Les images sont sauvegardées dans PLATEST/<nom_plaque>/
avec le nom de base de l'image source comme préfixe.

Exemple :
  python3 split_plate.py PLATEST/plate_bougie/bougie.jpg
  → PLATEST/plate_bougie/bougie_top.jpg
  → PLATEST/plate_bougie/bougie_bottom.jpg
  → PLATEST/plate_bougie/bougie_left.jpg
  → PLATEST/plate_bougie/bougie_right.jpg
"""
from __future__ import annotations
import argparse
from pathlib import Path
import cv2
import numpy as np


def split_image(src: Path, out_dir: Path, overlap: float = 0.15) -> list[Path]:
    img = cv2.imread(str(src))
    if img is None:
        raise FileNotFoundError(f"Image introuvable : {src}")

    h, w = img.shape[:2]
    ov_h = int(h * overlap)
    ov_w = int(w * overlap)
    stem = src.stem

    crops = {
        "top":    img[0          : h // 2 + ov_h, :],
        "bottom": img[h // 2 - ov_h : h,          :],
        "left":   img[:,            0          : w // 2 + ov_w],
        "right":  img[:,            w // 2 - ov_w : w],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for name, crop in crops.items():
        out_path = out_dir / f"{stem}_{name}.jpg"
        cv2.imwrite(str(out_path), crop)
        saved.append(out_path)
        print(f"  [{name:8s}] {crop.shape[1]}x{crop.shape[0]}  →  {out_path}")

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Split une image de plaque en 4 crops.")
    parser.add_argument("image",    help="Chemin vers l'image source")
    parser.add_argument("--platest", default=None,
                        help="Dossier PLATEST (défaut : dossier parent de l'image)")
    parser.add_argument("--overlap", type=float, default=0.15,
                        help="Fraction de chevauchement (défaut : 0.15)")
    args = parser.parse_args()

    src = Path(args.image)
    if not src.exists():
        print(f"[split] Erreur : fichier introuvable : {src}")
        return

    # Déterminer le dossier de sortie
    if args.platest:
        # Mode explicit : PLATEST/<nom_dossier_parent>/
        out_dir = Path(args.platest) / src.parent.name
    else:
        # Défaut : même dossier que l'image source
        out_dir = src.parent

    print(f"[split] Source  : {src}")
    print(f"[split] Sortie  : {out_dir}")
    print(f"[split] Overlap : {args.overlap * 100:.0f}%")
    split_image(src, out_dir, args.overlap)
    print(f"[split] Done ✔")


if __name__ == "__main__":
    main()
