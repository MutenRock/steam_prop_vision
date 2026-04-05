"""
tools/feature_gui.py
GUI Tkinter leger pour activer/desactiver les features S.T.E.A.M.
Pas de dependances externes — juste Tkinter (inclus avec Python).

Usage :
  python tools/feature_gui.py
  python tools/feature_gui.py --config config/features.yaml
"""
import tkinter as tk
from tkinter import ttk, messagebox
import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml

CONFIG_PATH = "config/features.yaml"

FEATURE_GROUPS = [
    ("Pipeline", [
        ("card_first",       "Detecter carte en premier (joueur = validation)", bool),
        ("require_person",   "Exiger presence joueur pour trigger",             bool),
    ]),
    ("Timing", [
        ("person_duration",   "Duree presence joueur (s)",  float),
        ("persist_after_loss","Persistance apres depart (s)", float),
        ("inspect_timeout",   "Timeout inspection (s)",      float),
        ("card_cooldown",     "Cooldown apres detection (s)",float),
    ]),
    ("Detection carte", [
        ("card_min_area",       "Aire minimale losange (px)", int),
        ("card_min_matches",    "Keypoints ORB minimum",      int),
        ("card_score_threshold","Score minimum ORB",          float),
    ]),
    ("Features optionnelles", [
        ("enable_movement_tracking", "Suivi deplacement joueur",  bool),
        ("enable_person_count",      "Log nb joueurs dans champ",  bool),
        ("enable_heartbeat",         "UDP heartbeat 5s",           bool),
        ("enable_monitor",           "WebSocket monitor :8889",     bool),
        ("enable_audio",             "Lecture audio",              bool),
        ("enable_video",             "Lecture video",              bool),
    ]),
    ("Reseau", [
        ("loxone_ip",   "IP Loxone",    str),
        ("loxone_port", "Port Loxone",  int),
    ]),
    ("Camera / YOLO", [
        ("camera_width",  "Largeur camera", int),
        ("camera_height", "Hauteur camera", int),
        ("yolo_imgsz",    "YOLO imgsz",     int),
        ("yolo_conf",     "YOLO conf",      float),
    ]),
]


class FeatureGUI:
    def __init__(self, root, config_path):
        self.root        = root
        self.config_path = Path(config_path)
        self.config      = self._load()
        self.vars        = {}

        root.title("S.T.E.A.M — Feature Manager")
        root.resizable(False, False)

        # Titre
        tk.Label(root, text="S.T.E.A.M Feature Manager",
                 font=("Helvetica", 13, "bold")).pack(pady=(10, 0))
        tk.Label(root, text=str(self.config_path),
                 font=("Helvetica", 8), fg="gray").pack()

        # Notebook (onglets par groupe)
        nb = ttk.Notebook(root)
        nb.pack(padx=10, pady=10, fill="both")

        for group_name, fields in FEATURE_GROUPS:
            frame = ttk.Frame(nb)
            nb.add(frame, text=group_name)
            for i, (key, label, typ) in enumerate(fields):
                val = self.config.get(key, "")
                self._build_row(frame, i, key, label, typ, val)

        # Boutons
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="Sauvegarder", width=16,
                  bg="#2d6a4f", fg="white", relief="flat",
                  command=self._save).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Recharger", width=14,
                  relief="flat",
                  command=self._reload).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Fermer", width=10,
                  relief="flat",
                  command=root.destroy).pack(side="left", padx=5)

        # Status
        self.status_var = tk.StringVar(value="Pret.")
        tk.Label(root, textvariable=self.status_var,
                 font=("Helvetica", 8), fg="gray").pack(pady=(0, 5))

    def _build_row(self, frame, row, key, label, typ, value):
        tk.Label(frame, text=label, anchor="w",
                 width=38).grid(row=row, column=0, sticky="w", padx=8, pady=3)

        if typ == bool:
            var = tk.BooleanVar(value=bool(value))
            tk.Checkbutton(frame, variable=var).grid(row=row, column=1, sticky="w")
        else:
            var = tk.StringVar(value=str(value))
            tk.Entry(frame, textvariable=var, width=12).grid(
                row=row, column=1, sticky="w", padx=4)

        self.vars[key] = (var, typ)

    def _load(self):
        if not self.config_path.exists():
            return {}
        with open(self.config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _save(self):
        for key, (var, typ) in self.vars.items():
            try:
                raw = var.get()
                self.config[key] = typ(raw) if typ != bool else bool(raw)
            except (ValueError, TypeError):
                messagebox.showerror("Erreur", "Valeur invalide pour : " + key)
                return
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False)
        self.status_var.set("Sauvegarde : " + str(self.config_path))

    def _reload(self):
        self.config = self._load()
        for key, (var, typ) in self.vars.items():
            val = self.config.get(key, "")
            if typ == bool:
                var.set(bool(val))
            else:
                var.set(str(val))
        self.status_var.set("Config rechargee.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=CONFIG_PATH)
    args = p.parse_args()

    root = tk.Tk()
    FeatureGUI(root, args.config)
    root.mainloop()


if __name__ == "__main__":
    main()
