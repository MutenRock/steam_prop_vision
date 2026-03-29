# Sim Env v4 – Presence + Plaque (Config Folder)

### Objectif
- Détecter **présence** (personne ou mouvement)
- Détecter une **plaque** via des images de référence dans un dossier de config
- Déclencher des actions (ici: injection d'un label vers la FSM)

### Installation
```bash
pip install -r requirements.txt
python -m gui.app
```

### Dossier de config
```
my_config/
  config.json
  plaques/
    plaque_A.png
    plaque_B.jpg
```

Un exemple est fourni dans `example_config/` (ajoute tes propres images).

### Notes
- Présence:
  - `yolo_person` (si ultralytics installé)
  - `motion` (léger, mais plus sensible aux faux positifs)
- Plaques: ORB feature matching (baseline sans entrainement)
  - marche mieux avec motifs distinctifs
  - si tu veux du "béton" -> ArUco/AprilTag


## Config Builder (nouveau)

Un second panel (séparé du GUI principal) te permet de **sélectionner plusieurs images** et **exporter un dossier config complet**.

Lancer :
```bash
python -m tools.config_builder_app
```

Le builder crée un dossier `config_YYYYMMDD_HHMMSS/` contenant :
- `config.json`
- `plaques/` avec les images copiées (et optionnellement redimensionnées)


## v5 – Rules / Actions

Le dossier de config peut maintenant contenir un `rules.json`.
Le GUI principal charge automatiquement ce fichier et exécute des actions quand :
- `presence` est validée (front montant)
- une `PLAQUE:<id>` est validée

Actions supportées (dans rules.json):
- `udp` (injecte un message UDP dans la simulation)
- `inject_detection` (injecte un label directement)
- `log`

Le **Config Builder** (tools/config_builder_app) exporte aussi `rules.json`.

## Windows – scripts .bat

### Installation rapide (venv)
- `install_venv.bat` : crée `.venv/` et installe les dépendances.

### Lancer
- `run_gui.bat` : lance le GUI principal
- `run_builder.bat` : lance le Config Builder

## Build EXE (PyInstaller)

Pré-requis :
- Windows
- Python installé
- Avoir fait `install_venv.bat`

Build :
- `build_gui_exe.bat` → `dist/SimEnv_MainGUI.exe`
- `build_builder_exe.bat` → `dist/SimEnv_ConfigBuilder.exe`
- `build_all_exe.bat` → build les deux

Notes :
- Le build peut être plus long au 1er run (PyInstaller + dépendances).
- Si tu utilises YOLO (`ultralytics`), l'exe peut être **gros** (torch).
