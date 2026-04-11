"""
tools/generate_samples.py
Genere un panel de N images augmentees depuis une image source.
"""
from __future__ import annotations
import argparse, random, sys
from pathlib import Path
import cv2
import numpy as np

PLATEST_DIR   = "PLATEST"
DEFAULT_COUNT = 15
WARP_SIZE     = 400


def _find_images(directory: Path) -> list[Path]:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.glob(ext))
    return imgs


def put(img, text, pos, color=(255,255,255), scale=0.45, thick=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)


def rotate(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w/2, h/2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def perspective_warp(img, strength=0.15):
    h, w = img.shape[:2]
    s    = strength
    mode = random.choice(["top","bottom","left","right","corner"])
    src  = np.float32([[0,0],[w,0],[w,h],[0,h]])
    d    = int(min(w,h)*s)
    if mode == "top":
        dst = np.float32([[d,d],[w-d,d],[w,h],[0,h]])
    elif mode == "bottom":
        dst = np.float32([[0,0],[w,0],[w-d,h-d],[d,h-d]])
    elif mode == "left":
        dst = np.float32([[d,d],[w,0],[w,h],[d,h-d]])
    elif mode == "right":
        dst = np.float32([[0,0],[w-d,d],[w-d,h-d],[0,h]])
    else:
        dst = np.float32([[d,d],[w-d//2,0],[w,h],[0,h-d//2]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w,h), borderMode=cv2.BORDER_REPLICATE)


def zoom_crop(img, factor):
    h, w   = img.shape[:2]
    new_h  = int(h*factor)
    new_w  = int(w*factor)
    resized = cv2.resize(img, (new_w, new_h))
    if factor > 1.0:
        y0 = (new_h-h)//2; x0 = (new_w-w)//2
        return resized[y0:y0+h, x0:x0+w]
    else:
        y0 = (h-new_h)//2; x0 = (w-new_w)//2
        return cv2.copyMakeBorder(resized, y0, h-new_h-y0,
                                  x0, w-new_w-x0, cv2.BORDER_REPLICATE)


def adjust_brightness(img, gamma):
    inv   = 1.0/gamma
    table = np.array([((i/255.0)**inv)*255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, table)


def add_blur(img, ksize):
    if ksize % 2 == 0: ksize += 1
    return cv2.GaussianBlur(img, (ksize, ksize), 0)


def add_noise(img, amount=0.02):
    noisy  = img.copy().astype(np.float32)
    n      = int(img.size * amount)
    coords = [np.random.randint(0, i, n) for i in img.shape[:2]]
    noisy[coords[0], coords[1]] = 255
    coords = [np.random.randint(0, i, n) for i in img.shape[:2]]
    noisy[coords[0], coords[1]] = 0
    return np.clip(noisy, 0, 255).astype(np.uint8)


def adjust_contrast(img, alpha, beta=0):
    return np.clip(img.astype(np.float32)*alpha+beta, 0, 255).astype(np.uint8)


def augment(img: np.ndarray, idx: int, total: int):
    out  = img.copy()
    tags = []
    angle = random.uniform(-30, 30)
    out   = rotate(out, angle)
    tags.append("rot" + str(round(angle)))
    if random.random() < 0.7:
        out = perspective_warp(out, random.uniform(0.05, 0.2))
        tags.append("persp")
    factor = random.uniform(0.75, 1.3)
    out    = zoom_crop(out, factor)
    tags.append("z" + str(round(factor,2)))
    gamma  = random.uniform(0.5, 2.0)
    out    = adjust_brightness(out, gamma)
    tags.append("g" + str(round(gamma,2)))
    alpha  = random.uniform(0.7, 1.4)
    out    = adjust_contrast(out, alpha)
    tags.append("c" + str(round(alpha,2)))
    if random.random() < 0.5:
        ksize = random.choice([3,5,7])
        out   = add_blur(out, ksize)
        tags.append("blur"+str(ksize))
    if random.random() < 0.4:
        out = add_noise(out, random.uniform(0.005, 0.03))
        tags.append("noise")
    if random.random() < 0.3:
        out = cv2.flip(out, 1)
        tags.append("flip")
    out = cv2.resize(out, (WARP_SIZE, WARP_SIZE))
    return out, "_".join(tags)


def make_contact_sheet(images, name):
    n    = len(images)
    cols = min(5, n)
    rows = (n+cols-1)//cols
    sz, pad = 160, 4
    W = cols*(sz+pad)+pad
    H = rows*(sz+pad)+pad+30
    sheet = np.zeros((H, W, 3), dtype=np.uint8)
    put(sheet, name + " -- " + str(n) + " samples", (pad, 20), (0,200,220), 0.55, 1)
    for i, img in enumerate(images):
        row = i//cols; col = i%cols
        x   = pad + col*(sz+pad)
        y   = 30  + pad + row*(sz+pad)
        thumb = cv2.resize(img, (sz, sz))
        sheet[y:y+sz, x:x+sz] = thumb
        put(sheet, str(i+1), (x+4, y+16), (200,200,200), 0.4)
    return sheet


def process_dir(input_dir: Path, count: int, seed):
    all_imgs = _find_images(input_dir)
    sources  = [p for p in all_imgs
                if not p.stem.startswith("sample_") and
                   not p.stem.startswith("aug_") and
                   p.name != "preview_augmented.jpg"]
    if not sources:
        print("[gen] " + str(input_dir) + " : aucune source trouvee")
        return 0
    print("[gen] " + input_dir.name + " : " +
          str(len(sources)) + " source(s) -> " + str(count) + " augmentations")
    if seed is not None:
        random.seed(seed); np.random.seed(seed)
    generated  = []
    per_source = max(1, count//len(sources))
    extra      = count - per_source*len(sources)
    for si, src_path in enumerate(sources):
        src = cv2.imread(str(src_path))
        if src is None:
            print("[gen] impossible de lire : " + str(src_path))
            continue
        n = per_source + (1 if si < extra else 0)
        for i in range(n):
            aug, tags = augment(src, i, n)
            out_name  = "aug_" + src_path.stem + "_" + str(i).zfill(3) + ".jpg"
            cv2.imwrite(str(input_dir/out_name), aug)
            generated.append(aug)
    print("[gen] " + str(len(generated)) + " images -> " + str(input_dir))
    if generated:
        sheet = make_contact_sheet(generated, input_dir.name)
        cv2.imwrite(str(input_dir/"preview_augmented.jpg"), sheet)
        print("[gen] Preview -> " + str(input_dir/"preview_augmented.jpg"))
        cv2.imshow("Augmentation : " + input_dir.name, sheet)
        cv2.waitKey(800)
    return len(generated)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", "-i")
    p.add_argument("--all",   "-a", action="store_true")
    p.add_argument("--count", "-n", type=int, default=DEFAULT_COUNT)
    p.add_argument("--out",   "-o")
    p.add_argument("--seed",  type=int, default=None)
    p.add_argument("--platest", default=PLATEST_DIR)
    args = p.parse_args()
    if not args.input and not args.all:
        p.print_help()
        return
    total = 0
    if args.all:
        base = Path(args.platest)
        if not base.exists():
            print("[gen] PLATEST introuvable : " + str(base)); return
        for d in sorted(d for d in base.iterdir() if d.is_dir()):
            n = process_dir(d, args.count, args.seed)
            total += n or 0
    elif args.input:
        inp = Path(args.input)
        if inp.is_dir():
            total = process_dir(inp, args.count, args.seed) or 0
        elif inp.is_file():
            out_dir = Path(args.out) if args.out else inp.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            src = cv2.imread(str(inp))
            if src is None:
                print("[gen] Impossible de lire : " + str(inp)); return
            if args.seed is not None:
                random.seed(args.seed); np.random.seed(args.seed)
            generated = []
            for i in range(args.count):
                aug, _ = augment(src, i, args.count)
                out_name = "aug_" + inp.stem + "_" + str(i).zfill(3) + ".jpg"
                cv2.imwrite(str(out_dir/out_name), aug)
                generated.append(aug)
                total += 1
            print("[gen] " + str(total) + " images -> " + str(out_dir))
            sheet = make_contact_sheet(generated, inp.stem)
            cv2.imwrite(str(out_dir/"preview_augmented.jpg"), sheet)
            cv2.imshow("Augmentation : " + inp.stem, sheet)
            cv2.waitKey(0)
    cv2.destroyAllWindows()
    print()
    print("[gen] Total : " + str(total) + " images generees.")


if __name__ == "__main__":
    main()
