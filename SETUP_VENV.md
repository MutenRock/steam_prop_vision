# system-packages.pth

Ce fichier permet au venv Python 3.13 d'acceder aux packages systeme (picamera2, libcamera...).

## Creation sur STYX (apres git pull)

```bash
echo "/usr/lib/python3/dist-packages" >> .venv/lib/python3.13/site-packages/system-packages.pth
```

## Verification

```bash
source .venv/bin/activate
python3 -c "from picamera2 import Picamera2; print('OK')"
```
