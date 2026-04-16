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
    return sorted(p.stem for p in PLATEST_DIR.iterdir()
                  if p.suffix.lower() in (".jpg", ".png"))


def scan_videos() -> list[str]:
    if not ASSETS_DIR.exists():
        return []
    return sorted(p.name for p in ASSETS_DIR.iterdir()
                  if p.suffix.lower() in (".mp4", ".mkv", ".avi"))


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"udp_port": 5005, "cards": []}


def save_and_launch(rows: list, udp_var: tk.StringVar, root: tk.Tk) -> None:
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
        messagebox.showerror("Erreur", "Aucune carte configurée.")
        return

    try:
        port = int(udp_var.get())
    except ValueError:
        messagebox.showerror("Erreur", "Port UDP invalide.")
        return

    config = {"udp_port": port, "cards": cards}
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[setup] config.json écrit ({len(cards)} cartes)")
    root.destroy()
    subprocess.Popen([sys.executable, str(Path(__file__).parent / "main.py")])


def build_gui() -> None:
    cfg       = load_config()
    templates = scan_templates()
    videos    = scan_videos()
    existing  = cfg.get("cards", [])

    # Si aucun template trouvé, on avertit
    if not templates:
        print("[setup] Aucun template trouvé dans PLATEST/")

    root = tk.Tk()
    root.title("S.T.E.A.M Vision — Setup")
    root.configure(bg="#1a1a2e")
    root.resizable(False, False)

    # ── Styles ──────────────────────────────────────────────────────────────
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame",    background="#1a1a2e")
    style.configure("TLabel",    background="#1a1a2e", foreground="#e0e0e0",
                    font=("Courier", 10))
    style.configure("TButton",   background="#16213e", foreground="#00d4ff",
                    font=("Courier", 11, "bold"), padding=8)
    style.configure("TCombobox", fieldbackground="#16213e", foreground="#e0e0e0",
                    background="#16213e")
    style.configure("TEntry",    fieldbackground="#16213e", foreground="#e0e0e0")

    # ── Header ───────────────────────────────────────────────────────────────
    tk.Label(root, text="⚙  S.T.E.A.M Vision  v2",
             bg="#1a1a2e", fg="#00d4ff",
             font=("Courier", 15, "bold")).pack(pady=(16, 6))

    # ── UDP port ─────────────────────────────────────────────────────────────
    top = ttk.Frame(root)
    top.pack(padx=24, pady=4, fill="x")
    ttk.Label(top, text="UDP broadcast port :").pack(side="left")
    udp_var = tk.StringVar(value=str(cfg.get("udp_port", 5005)))
    ttk.Entry(top, textvariable=udp_var, width=8).pack(side="left", padx=8)

    # ── Tableau cartes ───────────────────────────────────────────────────────
    frame = ttk.Frame(root)
    frame.pack(padx=24, pady=(12, 4))

    for col, txt in enumerate(["Template (PLATEST)", "Vidéo (assets/videos)", "Texte affiché"]):
        ttk.Label(frame, text=txt, foreground="#00d4ff").grid(
            row=0, column=col, padx=8, pady=4, sticky="w")

    rows: list = []

    # Construire une ligne par template disponible
    for i, tpl_id in enumerate(templates):
        # Chercher config existante pour ce template
        saved = next((c for c in existing if c["id"] == tpl_id), {})

        tpl_var = tk.StringVar(value=tpl_id)
        vid_var = tk.StringVar(
            value=Path(saved.get("video", "")).name if saved.get("video") else
                  (videos[0] if videos else "")
        )
        lbl_var = tk.StringVar(value=saved.get("label", ""))

        # Template label (non éditable)
        ttk.Label(frame, text=tpl_id, foreground="#aaffcc").grid(
            row=i+1, column=0, padx=8, pady=3, sticky="w")
        ttk.Combobox(frame, textvariable=vid_var, values=videos,
                     width=26, state="readonly").grid(
            row=i+1, column=1, padx=8, pady=3)
        ttk.Entry(frame, textvariable=lbl_var, width=32).grid(
            row=i+1, column=2, padx=8, pady=3)

        rows.append((tpl_var, vid_var, lbl_var))

    # ── Bouton lancer ────────────────────────────────────────────────────────
    ttk.Button(
        root, text="▶   Lancer la détection",
        command=lambda: save_and_launch(rows, udp_var, root)
    ).pack(pady=(16, 24))

    root.mainloop()


if __name__ == "__main__":
    build_gui()
