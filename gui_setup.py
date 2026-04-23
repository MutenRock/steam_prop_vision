# gui_setup.py - S.T.E.A.M Vision v2
from __future__ import annotations
import json, subprocess, sys, os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
PLATEST_DIR = Path(__file__).parent / "PLATEST"
ASSETS_DIR  = Path(__file__).parent / "assets" / "video"


def scan_templates() -> list[str]:
    if not PLATEST_DIR.exists():
        return []
    return sorted(p.name for p in PLATEST_DIR.iterdir() if p.is_dir())


def scan_all_videos() -> dict[str, Path]:
    exts = (".mp4", ".mkv", ".avi")
    result = {}
    if not ASSETS_DIR.exists():
        return result
    for p in sorted(ASSETS_DIR.rglob("*")):
        if p.suffix.lower() in exts:
            label = str(p.relative_to(ASSETS_DIR))
            result[label] = p
    return result


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        "udp_port": 5005,
        "idle_text": "Qu'avez vous \u00e0 me pr\u00e9senter voyageur du temps ?",
        "detection": {"min_quadrants": 2, "quad_min_matches": 4, "quad_threshold": 0.03},
        "cards": [],
    }


def save_and_launch(rows: list, udp_var: tk.StringVar, idle_var: tk.StringVar,
                    det_vars: dict, mode: str, root: tk.Tk, video_map: dict) -> None:
    cards = []
    for tpl_var, vid_var, lbl_var in rows:
        tpl = tpl_var.get().strip()
        vid = vid_var.get().strip()
        lbl = lbl_var.get().strip()
        if not tpl or not vid:
            continue
        full_path = video_map.get(vid, "")
        cards.append({"id": tpl, "video": str(full_path), "label": lbl})

    if not cards:
        messagebox.showerror("Erreur", "Aucune carte configur\u00e9e.")
        return
    try:
        port = int(udp_var.get())
    except ValueError:
        messagebox.showerror("Erreur", "Port UDP invalide.")
        return
    try:
        detection = {
            "min_quadrants":    int(det_vars["min_quadrants"].get()),
            "quad_min_matches": int(det_vars["quad_min_matches"].get()),
            "quad_threshold":   float(det_vars["quad_threshold"].get()),
        }
    except ValueError:
        messagebox.showerror("Erreur", "Param\u00e8tres de d\u00e9tection invalides.")
        return

    config = {
        "udp_port":  port,
        "idle_text": idle_var.get().strip(),
        "detection": detection,
        "cards":     cards,
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[setup] config.json \u00e9crit ({len(cards)} cartes) \u2014 mode {mode}")
    root.destroy()
    subprocess.Popen([sys.executable, str(Path(__file__).parent / "main.py"), f"--{mode}"])


def build_gui() -> None:
    cfg        = load_config()
    templates  = scan_templates()
    video_map  = scan_all_videos()
    vlabels    = list(video_map.keys())
    existing   = cfg.get("cards", [])
    det_cfg    = cfg.get("detection", {})

    print(f"[setup] Cartes PLATEST ({len(templates)}) :")
    for t in templates:
        print(f"  - {t}")
    print(f"[setup] Vid\u00e9os assets/video/ ({len(vlabels)}) :")
    for v in vlabels:
        print(f"  - {v}")

    root = tk.Tk()
    root.title("S.T.E.A.M Vision \u2014 Setup")
    root.configure(bg="#1a1a2e")
    root.resizable(False, False)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame",        background="#1a1a2e")
    style.configure("TLabel",        background="#1a1a2e", foreground="#e0e0e0", font=("Courier", 10))
    style.configure("TButton",       background="#16213e", foreground="#00d4ff", font=("Courier", 11, "bold"), padding=8)
    style.configure("Escape.TButton",background="#1a0a2e", foreground="#ff6ec7", font=("Courier", 13, "bold"), padding=12)
    style.configure("Debug.TButton", background="#0a1e2e", foreground="#00ff99", font=("Courier", 13, "bold"), padding=12)
    style.configure("Add.TButton",   background="#0a2e1e", foreground="#44ffaa", font=("Courier", 11, "bold"), padding=8)
    style.configure("Quit.TButton",  background="#2e0a0a", foreground="#ff4444", font=("Courier", 11, "bold"), padding=8)
    style.configure("Sep.TLabel",    background="#1a1a2e", foreground="#444466", font=("Courier", 9))
    style.configure("TCombobox", fieldbackground="#16213e", foreground="#e0e0e0", background="#16213e")
    style.configure("TEntry",    fieldbackground="#16213e", foreground="#e0e0e0")

    tk.Label(root, text="\u2699  S.T.E.A.M Vision  v2",
             bg="#1a1a2e", fg="#00d4ff", font=("Courier", 15, "bold")).pack(pady=(16, 6))

    # UDP
    top = ttk.Frame(root)
    top.pack(padx=24, pady=4, fill="x")
    ttk.Label(top, text="UDP broadcast port :").pack(side="left")
    udp_var = tk.StringVar(value=str(cfg.get("udp_port", 5005)))
    ttk.Entry(top, textvariable=udp_var, width=8).pack(side="left", padx=8)

    # Idle text
    idle_frame = ttk.Frame(root)
    idle_frame.pack(padx=24, pady=4, fill="x")
    ttk.Label(idle_frame, text="Texte idle        :").pack(side="left")
    idle_var = tk.StringVar(value=cfg.get("idle_text",
        "Qu'avez vous \u00e0 me pr\u00e9senter voyageur du temps ?"))
    ttk.Entry(idle_frame, textvariable=idle_var, width=48).pack(side="left", padx=8)

    # ── Section détection
    tk.Label(root, text="\u25b6  Param\u00e8tres d\u00e9tection",
             bg="#1a1a2e", fg="#ffcc44", font=("Courier", 10, "bold")).pack(pady=(10, 2))
    det_frame = ttk.Frame(root)
    det_frame.pack(padx=24, pady=4)

    det_vars = {}
    det_fields = [
        ("min_quadrants",    "Quadrants min valides (1-4) :", str(det_cfg.get("min_quadrants",    2))),
        ("quad_min_matches", "Matches min / quadrant      :", str(det_cfg.get("quad_min_matches", 4))),
        ("quad_threshold",   "Score seuil / quadrant      :", str(det_cfg.get("quad_threshold",   0.03))),
    ]
    for row_i, (key, label, default) in enumerate(det_fields):
        ttk.Label(det_frame, text=label).grid(row=row_i, column=0, sticky="w", padx=4, pady=2)
        var = tk.StringVar(value=default)
        ttk.Entry(det_frame, textvariable=var, width=8).grid(row=row_i, column=1, padx=8, pady=2)
        det_vars[key] = var

    # ── Tableau cartes
    tk.Label(root, text="\u25b6  Cartes",
             bg="#1a1a2e", fg="#ffcc44", font=("Courier", 10, "bold")).pack(pady=(10, 2))
    frame = ttk.Frame(root)
    frame.pack(padx=24, pady=(4, 4))
    for col, txt in enumerate(["Template", "Vid\u00e9o", "Texte d\u00e9tection"]):
        ttk.Label(frame, text=txt, foreground="#00d4ff").grid(
            row=0, column=col, padx=8, pady=4, sticky="w")

    rows: list = []
    for i, tpl_id in enumerate(templates):
        saved = next((c for c in existing if c["id"] == tpl_id), {})
        tpl_var = tk.StringVar(value=tpl_id)
        saved_path = saved.get("video", "")
        saved_label = ""
        if saved_path:
            try:
                saved_label = str(Path(saved_path).relative_to(ASSETS_DIR))
            except ValueError:
                saved_label = Path(saved_path).name
        vid_var = tk.StringVar(
            value=saved_label if saved_label in video_map else (vlabels[0] if vlabels else ""))
        lbl_var = tk.StringVar(value=saved.get("label", ""))
        ttk.Label(frame, text=tpl_id, foreground="#aaffcc").grid(
            row=i+1, column=0, padx=8, pady=3, sticky="w")
        ttk.Combobox(frame, textvariable=vid_var, values=vlabels,
                     width=32, state="readonly").grid(row=i+1, column=1, padx=8, pady=3)
        ttk.Entry(frame, textvariable=lbl_var, width=32).grid(
            row=i+1, column=2, padx=8, pady=3)
        rows.append((tpl_var, vid_var, lbl_var))

    # ── Bouton add/update plate
    def open_add_plate_dialog() -> None:
        name = simpledialog.askstring(
            "Ajouter / mettre à jour une plate",
            "Nom de la plate (ex: bougie) :",
            parent=root
        )
        if not name:
            return
        name = name.strip().lower()
        if not name:
            return
        img = filedialog.askopenfilename(
            title="Choisir l'image source",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("Tous", "*.*")]
        )
        if not img:
            return
        script = Path(__file__).parent / "add_plate.sh"
        try:
            result = subprocess.run(
                ["bash", str(script), name, img],
                cwd=str(Path(__file__).parent),
                capture_output=True, text=True
            )
        except Exception as e:
            messagebox.showerror("Erreur add_plate", str(e))
            return
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0:
            messagebox.showerror("Erreur add_plate", output.strip() or "Erreur inconnue")
            return
        messagebox.showinfo(
            "Plate ajoutée ✅",
            (output.strip() or "Done.") + "\n\nLe setup va se recharger."
        )
        root.destroy()
        subprocess.Popen([sys.executable, str(Path(__file__).parent / "gui_setup.py")])

    # ── Boutons lancement
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=(16, 8))
    ttk.Button(btn_frame, text="\U0001f3ae  Mode ESCAPE", style="Escape.TButton",
               command=lambda: save_and_launch(rows, udp_var, idle_var, det_vars, "escape", root, video_map)
               ).pack(side="left", padx=12)
    ttk.Button(btn_frame, text="\U0001f50d  Mode DEBUG", style="Debug.TButton",
               command=lambda: save_and_launch(rows, udp_var, idle_var, det_vars, "debug", root, video_map)
               ).pack(side="left", padx=12)

    ttk.Button(root, text="\u2295  Ajouter / mettre \u00e0 jour une plate", style="Add.TButton",
               command=open_add_plate_dialog).pack(pady=(4, 4))

    ttk.Button(root, text="\u2716  Quitter", style="Quit.TButton",
               command=lambda: os._exit(0)).pack(pady=(4, 20))

    root.mainloop()


if __name__ == "__main__":
    build_gui()