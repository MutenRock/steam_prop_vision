# gui_setup.py - S.T.E.A.M Vision v2
# GUI Tkinter pre-lancement : configure config.json puis lance main.py
from __future__ import annotations
import json, subprocess, sys
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
PLATEST_DIR = Path(__file__).parent / "PLATEST"
ASSETS_DIR  = Path(__file__).parent / "assets" / "videos"


def scan_templates() -> list[str]:
    if not PLATEST_DIR.exists():
        return []
    return sorted(p.name for p in PLATEST_DIR.iterdir() if p.is_dir())


def scan_videos() -> list[str]:
    if not ASSETS_DIR.exists():
        return []
    return sorted(p.name for p in ASSETS_DIR.iterdir()
                  if p.suffix.lower() in (".mp4", ".mkv", ".avi"))


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"udp_port": 5005, "idle_text": "Qu'avez vous \u00e0 me pr\u00e9senter voyageur du temps ?", "cards": []}


def save_and_launch(rows: list, udp_var: tk.StringVar,
                    idle_var: tk.StringVar, mode: str, root: tk.Tk) -> None:
    cards = []
    for tpl_var, vid_var, lbl_var in rows:
        tpl = tpl_var.get().strip()
        vid = vid_var.get().strip()
        lbl = lbl_var.get().strip()
        if not tpl or not vid:
            continue
        cards.append({
            "id":    tpl,
            "video": str(ASSETS_DIR / vid),
            "label": lbl,
        })

    if not cards:
        messagebox.showerror("Erreur", "Aucune carte configur\u00e9e.")
        return
    try:
        port = int(udp_var.get())
    except ValueError:
        messagebox.showerror("Erreur", "Port UDP invalide.")
        return

    config = {
        "udp_port":  port,
        "idle_text": idle_var.get().strip(),
        "cards":     cards,
    }
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[setup] config.json \u00e9crit ({len(cards)} cartes) — mode {mode}")
    root.destroy()
    subprocess.Popen([sys.executable,
                      str(Path(__file__).parent / "main.py"),
                      f"--{mode}"])


def build_gui() -> None:
    cfg       = load_config()
    templates = scan_templates()
    videos    = scan_videos()
    existing  = cfg.get("cards", [])

    if not templates:
        print("[setup] Aucun sous-dossier trouv\u00e9 dans PLATEST/")

    root = tk.Tk()
    root.title("S.T.E.A.M Vision \u2014 Setup")
    root.configure(bg="#1a1a2e")
    root.resizable(False, False)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame",    background="#1a1a2e")
    style.configure("TLabel",    background="#1a1a2e", foreground="#e0e0e0",
                    font=("Courier", 10))
    style.configure("TButton",   background="#16213e", foreground="#00d4ff",
                    font=("Courier", 11, "bold"), padding=8)
    style.configure("Escape.TButton", background="#1a0a2e", foreground="#ff6ec7",
                    font=("Courier", 13, "bold"), padding=12)
    style.configure("Debug.TButton",  background="#0a1e2e", foreground="#00ff99",
                    font=("Courier", 13, "bold"), padding=12)
    style.configure("TCombobox", fieldbackground="#16213e", foreground="#e0e0e0",
                    background="#16213e")
    style.configure("TEntry",    fieldbackground="#16213e", foreground="#e0e0e0")

    # ── Header
    tk.Label(root, text="\u2699  S.T.E.A.M Vision  v2",
             bg="#1a1a2e", fg="#00d4ff",
             font=("Courier", 15, "bold")).pack(pady=(16, 6))

    # ── UDP port
    top = ttk.Frame(root)
    top.pack(padx=24, pady=4, fill="x")
    ttk.Label(top, text="UDP broadcast port :").pack(side="left")
    udp_var = tk.StringVar(value=str(cfg.get("udp_port", 5005)))
    ttk.Entry(top, textvariable=udp_var, width=8).pack(side="left", padx=8)

    # ── Idle text
    idle_frame = ttk.Frame(root)
    idle_frame.pack(padx=24, pady=4, fill="x")
    ttk.Label(idle_frame, text="Texte idle        :").pack(side="left")
    idle_var = tk.StringVar(value=cfg.get("idle_text",
        "Qu'avez vous \u00e0 me pr\u00e9senter voyageur du temps ?"))
    ttk.Entry(idle_frame, textvariable=idle_var, width=48).pack(side="left", padx=8)

    # ── Tableau cartes
    frame = ttk.Frame(root)
    frame.pack(padx=24, pady=(12, 4))
    for col, txt in enumerate(["Template", "Vid\u00e9o", "Texte d\u00e9tection"]):
        ttk.Label(frame, text=txt, foreground="#00d4ff").grid(
            row=0, column=col, padx=8, pady=4, sticky="w")

    rows: list = []
    for i, tpl_id in enumerate(templates):
        saved   = next((c for c in existing if c["id"] == tpl_id), {})
        tpl_var = tk.StringVar(value=tpl_id)
        vid_var = tk.StringVar(
            value=Path(saved.get("video", "")).name if saved.get("video") else
                  (videos[0] if videos else ""))
        lbl_var = tk.StringVar(value=saved.get("label", ""))

        ttk.Label(frame, text=tpl_id, foreground="#aaffcc").grid(
            row=i+1, column=0, padx=8, pady=3, sticky="w")
        ttk.Combobox(frame, textvariable=vid_var, values=videos,
                     width=26, state="readonly").grid(row=i+1, column=1, padx=8, pady=3)
        ttk.Entry(frame, textvariable=lbl_var, width=32).grid(
            row=i+1, column=2, padx=8, pady=3)
        rows.append((tpl_var, vid_var, lbl_var))

    # ── Boutons mode
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=(16, 24))

    ttk.Button(
        btn_frame, text="\U0001f3ae  Mode ESCAPE",
        style="Escape.TButton",
        command=lambda: save_and_launch(rows, udp_var, idle_var, "escape", root)
    ).pack(side="left", padx=16)

    ttk.Button(
        btn_frame, text="\U0001f50d  Mode DEBUG",
        style="Debug.TButton",
        command=lambda: save_and_launch(rows, udp_var, idle_var, "debug", root)
    ).pack(side="left", padx=16)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
