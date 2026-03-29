# -*- coding: utf-8 -*-
"""
Config Builder GUI
------------------
Creates an exportable config folder for Sim Env v4+.

Outputs:
  <export_folder>/
      config.json
      plaques/
          plaque_A.png
          plaque_B.jpg
          ...

Features:
- Select multiple images
- Rename plaque IDs (base filename suggested)
- Optional resize (keeps aspect) for normalization
- Set presence / plaque / trigger parameters
"""

from __future__ import annotations
import os
import json
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from typing import List, Optional

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None


@dataclass
class PlaqueItem:
    src_path: str
    plaque_id: str
    out_ext: str


def _safe_id(s: str) -> str:
    keep = []
    for ch in s.strip():
        if ch.isalnum() or ch in ("_", "-", "."):
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep).strip("_")
    return out or "plaque"


class ConfigBuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sim Env – Config Builder (export folder)")
        self.geometry("980x720")
        self.minsize(900, 640)

        self.items: List[PlaqueItem] = []

        # settings vars
        self.presence_mode = tk.StringVar(value="yolo_person")
        self.presence_min_conf = tk.DoubleVar(value=0.65)
        self.presence_stable_frames = tk.IntVar(value=3)
        self.presence_cooldown_s = tk.DoubleVar(value=2.0)

        self.plaque_min_good_matches = tk.IntVar(value=18)
        self.plaque_stable_frames = tk.IntVar(value=2)
        self.plaque_cooldown_s = tk.DoubleVar(value=2.0)
        self.plaque_require_presence = tk.BooleanVar(value=True)

        self.trigger_start_on = tk.StringVar(value="PLAQUE")  # PLAQUE or PRESENCE
        self.allowed_plaque_ids = tk.StringVar(value="")  # comma separated, optional

        # rules json text
        self.rules_json_text = None

        self.enable_resize = tk.BooleanVar(value=False)
        self.resize_max_side = tk.IntVar(value=900)

        self.export_folder = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(top, text="Add images…", command=self._add_images).pack(side=tk.LEFT)
        ttk.Button(top, text="Remove selected", command=self._remove_selected).pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(top, text="Clear", command=self._clear).pack(side=tk.LEFT, padx=(8,0))

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(0,8))

        # list
        list_frame = ttk.LabelFrame(self, text="Plaques (source → plaque_id)")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)

        self.tree = ttk.Treeview(list_frame, columns=("src", "id", "ext"), show="headings", selectmode="extended")
        self.tree.heading("src", text="Source image")
        self.tree.heading("id", text="plaque_id (used in PLAQUE:<id>)")
        self.tree.heading("ext", text="Export ext")
        self.tree.column("src", width=560)
        self.tree.column("id", width=220)
        self.tree.column("ext", width=90, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        edit_row = ttk.Frame(list_frame)
        edit_row.pack(fill=tk.X, padx=8, pady=(0,8))
        ttk.Label(edit_row, text="Edit plaque_id for selected:").pack(side=tk.LEFT)
        self.edit_id = tk.StringVar(value="")
        ttk.Entry(edit_row, textvariable=self.edit_id, width=30).pack(side=tk.LEFT, padx=8)
        ttk.Button(edit_row, text="Apply", command=self._apply_id_to_selected).pack(side=tk.LEFT)

        # settings panels
        settings = ttk.Frame(self)
        settings.pack(fill=tk.X, padx=10, pady=10)

        pres = ttk.LabelFrame(settings, text="Presence settings")
        pres.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,8))

        ttk.Label(pres, text="Mode").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Combobox(pres, values=["yolo_person", "motion"], textvariable=self.presence_mode, state="readonly").grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(pres, text="min_conf").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pres, from_=0.1, to=0.99, increment=0.05, textvariable=self.presence_min_conf, width=8).grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(pres, text="stable_frames").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pres, from_=1, to=10, increment=1, textvariable=self.presence_stable_frames, width=8).grid(row=2, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(pres, text="cooldown_s").grid(row=3, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pres, from_=0.0, to=30.0, increment=0.5, textvariable=self.presence_cooldown_s, width=8).grid(row=3, column=1, padx=8, pady=6, sticky="w")

        pl = ttk.LabelFrame(settings, text="Plaque settings")
        pl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,8))

        ttk.Label(pl, text="min_good_matches").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pl, from_=5, to=200, increment=1, textvariable=self.plaque_min_good_matches, width=8).grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(pl, text="stable_frames").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pl, from_=1, to=10, increment=1, textvariable=self.plaque_stable_frames, width=8).grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(pl, text="cooldown_s").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        ttk.Spinbox(pl, from_=0.0, to=30.0, increment=0.5, textvariable=self.plaque_cooldown_s, width=8).grid(row=2, column=1, padx=8, pady=6, sticky="w")

        ttk.Checkbutton(pl, text="require_presence", variable=self.plaque_require_presence).grid(row=3, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        trig = ttk.LabelFrame(settings, text="Trigger / Export")
        trig.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(trig, text="start_on").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Combobox(trig, values=["PLAQUE", "PRESENCE"], textvariable=self.trigger_start_on, state="readonly").grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ttk.Label(trig, text="allowed_plaque_ids (optional, comma)").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(trig, textvariable=self.allowed_plaque_ids).grid(row=1, column=1, padx=8, pady=6, sticky="ew")

        ttk.Checkbutton(trig, text="Resize images on export", variable=self.enable_resize).grid(row=2, column=0, padx=8, pady=6, sticky="w")
        ttk.Label(trig, text="max side").grid(row=2, column=1, padx=(8,2), pady=6, sticky="w")
        ttk.Spinbox(trig, from_=200, to=3000, increment=50, textvariable=self.resize_max_side, width=8).grid(row=2, column=1, padx=(80,8), pady=6, sticky="w")

        ttk.Label(trig, text="Export folder").grid(row=3, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(trig, textvariable=self.export_folder).grid(row=3, column=1, padx=8, pady=6, sticky="ew")
        ttk.Button(trig, text="Browse", command=self._choose_export).grid(row=3, column=2, padx=8, pady=6)

        ttk.Button(trig, text="Export config folder", command=self._export).grid(row=4, column=1, padx=8, pady=(10,6), sticky="e")
        trig.columnconfigure(1, weight=1)

        
        # Rules editor
        rules_frame = ttk.LabelFrame(self, text="Rules (rules.json) – actions on presence / plaques")
        rules_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0,10))

        btn_row = ttk.Frame(rules_frame)
        btn_row.pack(fill=tk.X, padx=8, pady=(8,4))
        ttk.Button(btn_row, text="Generate default rules from plaques", command=self._gen_default_rules).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Load rules.json…", command=self._load_rules_json).pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(btn_row, text="Validate JSON", command=self._validate_rules_json).pack(side=tk.LEFT, padx=(8,0))

        self.rules_json_text = tk.Text(rules_frame, height=10, wrap="none")
        self.rules_json_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self.rules_json_text.insert("1.0", json.dumps({"version":1,"rules":[]}, indent=2, ensure_ascii=False))

        hint = ttk.Label(self, text="Tip: plaque_id is the filename (without extension) in export/plaques/. Use safe ids (letters/numbers/_).")
        hint.pack(anchor="w", padx=12, pady=(0,10))

    def _refresh_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for it in self.items:
            self.tree.insert("", "end", values=(it.src_path, it.plaque_id, it.out_ext))

    def _add_images(self):
        paths = filedialog.askopenfilenames(
            title="Select plaque reference images",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*")]
        )
        if not paths:
            return
        for p in paths:
            base = os.path.splitext(os.path.basename(p))[0]
            ext = os.path.splitext(p)[1].lower() or ".png"
            pid = _safe_id(base)
            self.items.append(PlaqueItem(src_path=p, plaque_id=pid, out_ext=ext))
        self._refresh_tree()

    def _remove_selected(self):
        sel = set(self.tree.selection())
        if not sel:
            return
        new_items = []
        for idx, iid in enumerate(self.tree.get_children()):
            if iid not in sel:
                new_items.append(self.items[idx])
        self.items = new_items
        self._refresh_tree()

    def _clear(self):
        self.items = []
        self._refresh_tree()

    def _apply_id_to_selected(self):
        new_id = _safe_id(self.edit_id.get())
        if not new_id:
            return
        sel = set(self.tree.selection())
        if not sel:
            return
        for idx, iid in enumerate(self.tree.get_children()):
            if iid in sel:
                self.items[idx].plaque_id = new_id
        self._refresh_tree()

    def _choose_export(self):
        folder = filedialog.askdirectory(title="Select export folder (will create a subfolder inside)")
        if folder:
            self.export_folder.set(folder)

    def _build_config_json(self) -> dict:
        allowed = [s.strip() for s in self.allowed_plaque_ids.get().split(",") if s.strip()]
        return {
            "presence": {
                "mode": self.presence_mode.get(),
                "min_conf": float(self.presence_min_conf.get()),
                "stable_frames": int(self.presence_stable_frames.get()),
                "cooldown_s": float(self.presence_cooldown_s.get()),
            },
            "plaque": {
                "min_good_matches": int(self.plaque_min_good_matches.get()),
                "stable_frames": int(self.plaque_stable_frames.get()),
                "cooldown_s": float(self.plaque_cooldown_s.get()),
                "require_presence": bool(self.plaque_require_presence.get()),
            },
            "trigger": {
                "start_on": self.trigger_start_on.get(),
                "allowed_plaque_ids": allowed,
            }
        }


    def _get_rules_json_obj(self) -> dict:
        if self.rules_json_text is None:
            return {"version": 1, "rules": []}
        raw = self.rules_json_text.get("1.0", "end").strip()
        if not raw:
            return {"version": 1, "rules": []}
        return json.loads(raw)

    def _validate_rules_json(self):
        try:
            obj = self._get_rules_json_obj()
            if not isinstance(obj, dict) or "rules" not in obj:
                raise ValueError("rules.json must be an object with a 'rules' list")
            messagebox.showinfo("OK", f"rules.json valid. rules count = {len(obj.get('rules', []))}")
        except Exception as e:
            messagebox.showerror("Invalid JSON", str(e))

    def _load_rules_json(self):
        path = filedialog.askopenfilename(
            title="Select rules.json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            self.rules_json_text.delete("1.0", "end")
            self.rules_json_text.insert("1.0", data)
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _gen_default_rules(self):
        """
        Generates a simple rules.json:
          - presence -> udp LOXONE:PRESENCE=1
          - for each plaque -> udp CMD:START (require_presence=true)
        """
        rules = [{"when": "presence", "cooldown_s": float(self.presence_cooldown_s.get()),
                  "then": [{"type": "udp", "msg": "LOXONE:PRESENCE=1"}]}]
        for it in self.items:
            rules.append({
                "when": f"PLAQUE:{it.plaque_id}",
                "require_presence": bool(self.plaque_require_presence.get()),
                "cooldown_s": float(self.plaque_cooldown_s.get()),
                "then": [{"type": "udp", "msg": "CMD:START"}]
            })
        obj = {"version": 1, "rules": rules}
        self.rules_json_text.delete("1.0", "end")
        self.rules_json_text.insert("1.0", json.dumps(obj, indent=2, ensure_ascii=False))

    def _export(self):
        if not self.items:
            messagebox.showwarning("No images", "Add at least one plaque image first.")
            return
        out_root = self.export_folder.get().strip()
        if not out_root:
            messagebox.showwarning("No export folder", "Choose an export folder.")
            return

        # create subfolder: config_<timestamp>
        import datetime as _dt
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_folder = os.path.join(out_root, f"config_{stamp}")
        plaques_out = os.path.join(out_folder, "plaques")

        try:
            os.makedirs(plaques_out, exist_ok=False)
        except FileExistsError:
            messagebox.showerror("Export error", f"Folder already exists: {out_folder}")
            return
        except Exception as e:
            messagebox.showerror("Export error", str(e))
            return

        # write config.json
        cfg = self._build_config_json()
        with open(os.path.join(out_folder, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        # write rules.json (v5)
        try:
            rules_obj = self._get_rules_json_obj()
            with open(os.path.join(out_folder, "rules.json"), "w", encoding="utf-8") as rf:
                json.dump(rules_obj, rf, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("rules.json error", f"Invalid rules.json: {e}")
            return

        # copy (and optionally resize) images
        resize = bool(self.enable_resize.get())
        max_side = int(self.resize_max_side.get())
        can_resize = resize and (Image is not None)

        for it in self.items:
            dst_name = f"{it.plaque_id}{it.out_ext}"
            dst_path = os.path.join(plaques_out, dst_name)

            if can_resize:
                try:
                    img = Image.open(it.src_path)
                    img = img.convert("RGB")
                    w, h = img.size
                    scale = max(w, h) / float(max_side)
                    if scale > 1.0:
                        nw = int(w / scale)
                        nh = int(h / scale)
                        img = img.resize((nw, nh))
                    # keep original ext if possible; Pillow supports PNG/JPEG well
                    save_ext = it.out_ext.lower()
                    if save_ext in (".jpg", ".jpeg"):
                        img.save(dst_path, quality=92)
                    else:
                        # default to PNG if weird ext
                        if save_ext not in (".png", ".webp", ".bmp", ".jpg", ".jpeg"):
                            dst_path = os.path.join(plaques_out, f"{it.plaque_id}.png")
                        img.save(dst_path)
                    continue
                except Exception:
                    # fallback to copy
                    pass

            shutil.copy2(it.src_path, dst_path)

        messagebox.showinfo("Export done", f"Config exported to:\n{out_folder}")

def main():
    app = ConfigBuilderApp()
    app.mainloop()

if __name__ == "__main__":
    main()
