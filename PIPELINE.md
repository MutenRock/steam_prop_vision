# S.T.E.A.M — Pipeline validé (BigEye benchmarks)

## Config matérielle STYX
- Raspberry Pi 5 8GB — Debian Trixie aarch64
- Pi Camera Module 3 IMX708 CSI
- Venv Python 3.13 avec --system-site-packages

## Perfs pipeline (headless, mesurées)
| Étape          | Avg    | FPS    |
|----------------|--------|--------|
| Picamera2 1280x720 | 9ms | 108 FPS |
| YOLO yolov8n.pt 320px | 55ms | 18 FPS |
| **Pipeline total** | **64ms** | **15.6 FPS** |

## Architecture pipeline
```
Picamera2 (1280x720)
    ↓ frame BGR
YOLODetector (imgsz=320, conf=0.5)
    ↓ 3 frames confirmées
AudioPlayer (ffplay MP3, non-bloquant)
    ↓
UDPSend → Loxone (STEAM_DETECT_PERSON)
    ↓
WSBridge → monitor/index.html (navigateur Salomon)
```

## Lancer
```bash
source .venv/bin/activate
python apps/rpi/main.py --loxone 192.168.1.50
# options : --no-udp --no-audio --no-heart
```

## Monitor (depuis Salomon)
Ouvrir `monitor/index.html` dans le navigateur,
entrer l'IP de STYX + port 8889, cliquer Connecter.
