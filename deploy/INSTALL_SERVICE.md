# Installation du service systemd — S.T.E.A.M Vision

## 1. Copier le fichier service

```bash
sudo cp deploy/steam-vision.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## 2. Activer et démarrer

```bash
sudo systemctl enable steam-vision   # lancement auto au boot
sudo systemctl start  steam-vision   # démarrage immédiat
```

## 3. Vérifier le statut

```bash
sudo systemctl status steam-vision
```

## 4. Lire les logs en temps réel

```bash
# Logs systemd (journal)
journalctl -u steam-vision -f

# Logs fichier rotatif (plus détaillés)
tail -f /home/steam/steam_prop_vision/logs/steam_vision.log
```

## 5. Arrêter / Redémarrer

```bash
sudo systemctl stop    steam-vision
sudo systemctl restart steam-vision
```

## 6. Désactiver le service

```bash
sudo systemctl disable steam-vision
```

## Notes

- **Restart=on-failure** : relance automatique si le processus crashe
- **RestartSec=5s** : attend 5s avant de relancer (évite les boucles)
- **StartLimitBurst=5** : max 5 relances en 60s — après, stoppe définitivement
  (évite la boucle infinie si le crash est structurel)
- Les logs sont disponibles via `journalctl` ET via `logs/steam_vision.log`
- `DISPLAY=:0` requis pour que mpv s'affiche sur le HDMI
