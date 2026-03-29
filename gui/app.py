# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core.sim_core import SimulationEngine
from gui.config_manager import load_config_folder, get_plaques_folder
from gui.rule_engine import RuleEngine
from gui.action_router import ActionRouter

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:
    Image = None
    ImageTk = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sim Env v4 – Presence + Plaque (Config Folder)")
        self.geometry("1320x860")

        self.engine = SimulationEngine()
        # router rules stay loaded; keeps current actions

        self.rules = RuleEngine()
        self.router = ActionRouter()
        self.rules_status = tk.StringVar(value="actions: (no rules loaded)")

        self.running = False
        self.dt = tk.DoubleVar(value=0.2)

        self.cam_enabled = tk.BooleanVar(value=True)
        self.cam_index = tk.IntVar(value=0)
        self._cap = None
        self._tk_cam_img = None

        self.config_folder = tk.StringVar(value="")
        self.loaded_plaques = tk.StringVar(value="plaques: (none)")
        self.trigger_mode = tk.StringVar(value="PLAQUE")  # PLAQUE or PRESENCE

        self._last_injected_presence = 0.0
        self._presence_inject_cooldown = 2.0

        self._presence_prev = False
        self._action_log_lines = []  # last action logs

        self._build_ui()
        self._restart_cam()
        self._refresh_ui()
        self.after(50, self._loop)

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.btn_run = ttk.Button(toolbar, text="Run", command=self._toggle_run)
        self.btn_run.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="Step", command=self._step_once).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(toolbar, text="Reset", command=self._reset).pack(side=tk.LEFT, padx=(6,0))

        ttk.Label(toolbar, text="dt(s):").pack(side=tk.LEFT, padx=(18,4))
        ttk.Spinbox(toolbar, from_=0.05, to=2.0, increment=0.05, textvariable=self.dt, width=6).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)
        ttk.Checkbutton(toolbar, text="PC Cam", variable=self.cam_enabled, command=self._on_cam_toggle).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="Index:").pack(side=tk.LEFT, padx=(8,4))
        ttk.Spinbox(toolbar, from_=0, to=5, textvariable=self.cam_index, width=3, command=self._restart_cam).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)
        ttk.Button(toolbar, text="Load Config Folder", command=self._load_config_folder).pack(side=tk.LEFT)
        ttk.Label(toolbar, textvariable=self.loaded_plaques).pack(side=tk.LEFT, padx=(10,0))
        ttk.Label(toolbar, textvariable=self.rules_status).pack(side=tk.LEFT, padx=(10,0))

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        cfg = ttk.LabelFrame(left, text="Config / Modes")
        cfg.pack(fill=tk.X)

        ttk.Label(cfg, text="Config folder:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.config_folder).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ttk.Button(cfg, text="Browse", command=self._load_config_folder).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(cfg, text="Presence mode:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.cmb_presence = ttk.Combobox(cfg, values=["yolo_person","motion"], state="readonly")
        self.cmb_presence.set("yolo_person")
        self.cmb_presence.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(cfg, text="Trigger start on:").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        self.cmb_trigger = ttk.Combobox(cfg, values=["PLAQUE","PRESENCE"], textvariable=self.trigger_mode, state="readonly")
        self.cmb_trigger.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ttk.Button(cfg, text="Apply UI modes", command=self._apply_ui_modes).grid(row=3, column=1, padx=6, pady=6, sticky="w")
        cfg.columnconfigure(1, weight=1)

        live = ttk.LabelFrame(left, text="Live Recognition Status")
        live.pack(fill=tk.X, pady=(10,0))
        self.lbl_presence = ttk.Label(live, text="Presence: -")
        self.lbl_presence.pack(anchor="w", padx=10, pady=(6,2))
        self.lbl_plaque = ttk.Label(live, text="Plaque: -")
        self.lbl_plaque.pack(anchor="w", padx=10, pady=(0,6))

        inj = ttk.LabelFrame(left, text="Manual Inject (tests)")
        inj.pack(fill=tk.X, pady=(10,0))
        self.manual_label = tk.StringVar(value="PLAQUE:plaque_A")
        self.manual_conf = tk.DoubleVar(value=0.9)
        row = ttk.Frame(inj)
        row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Entry(row, textvariable=self.manual_label).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Spinbox(row, from_=0.0, to=1.0, increment=0.05, textvariable=self.manual_conf, width=6).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Inject", command=self._manual_inject).pack(side=tk.LEFT)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        top_right = ttk.Frame(right)
        top_right.pack(fill=tk.BOTH, expand=False)

        snap = ttk.LabelFrame(top_right, text="System State")
        snap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,8))
        self.lbl_time = ttk.Label(snap, text="t=0.0", font=("Segoe UI", 12, "bold"))
        self.lbl_time.pack(anchor="w", padx=10, pady=(8,2))
        self.lbl_fsm = ttk.Label(snap, text="FSM: IDLE")
        self.lbl_fsm.pack(anchor="w", padx=10)
        self.lbl_last = ttk.Label(snap, text="Last injected: -")
        self.lbl_actions = ttk.Label(snap, text="Actions: -")
        self.lbl_actions.pack(anchor="w", padx=10)
        self.lbl_last.pack(anchor="w", padx=10)
        self.lbl_player = ttk.Label(snap, text="Player: stopped")
        self.lbl_player.pack(anchor="w", padx=10, pady=(0,8))

        cam = ttk.LabelFrame(top_right, text="PC Camera Preview")
        cam.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        self.cam_label = ttk.Label(cam)
        self.cam_label.pack(padx=8, pady=8)
        self._set_cam_placeholder()

        log_frame = ttk.LabelFrame(right, text="Logs (tail)")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8,0))
        self.txt_log = tk.Text(log_frame, height=20, wrap="none")
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.configure(state="disabled")
        yscroll = ttk.Scrollbar(self.txt_log, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _toggle_run(self):
        self.running = not self.running
        self.btn_run.configure(text="Pause" if self.running else "Run")

    def _step_once(self):
        self.engine.step(float(self.dt.get()))
        self._refresh_ui()

    def _reset(self):
        self.running = False
        self.btn_run.configure(text="Run")
        self.engine = SimulationEngine()
        # router rules stay loaded; keeps current actions

        self._refresh_ui()

    def _manual_inject(self):
        self.engine.inject_detection(self.manual_label.get(), float(self.manual_conf.get()))
        self._refresh_ui()

    def _apply_ui_modes(self):
        self.rules.presence.mode = self.cmb_presence.get().strip()
        if self.trigger_mode.get() == "PRESENCE":
            self.engine.set_trigger_labels(["presence"])
        else:
            self.engine.set_trigger_labels(None)
        messagebox.showinfo("Applied", "UI modes applied.")

    def _load_config_folder(self):
        folder = filedialog.askdirectory(title="Select config folder (config.json + plaques/)")
        if not folder:
            return
        try:
            loaded = load_config_folder(folder)
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            return

        self.config_folder.set(folder)
        self.rules.apply_config(loaded.data)
        self.cmb_presence.set(self.rules.presence.mode)

        plaques_folder = get_plaques_folder(folder)
        if not os.path.isdir(plaques_folder):
            messagebox.showwarning("Missing plaques/", f"No plaques folder found at: {plaques_folder}")
            loaded_ids = []
        else:
            loaded_ids = self.rules.plaque.load_from_folder(plaques_folder)

        self.loaded_plaques.set(f"plaques: {len(loaded_ids)} loaded")

        ok, msg = self.router.load_rules(folder)
        self.rules_status.set("actions: " + msg)

        trig = loaded.data.get("trigger", {})
        start_on = trig.get("start_on", "PLAQUE")
        self.trigger_mode.set(start_on if start_on in ("PLAQUE","PRESENCE") else "PLAQUE")
        self._apply_ui_modes()

    def _on_cam_toggle(self):
        if self.cam_enabled.get():
            self._restart_cam()
        else:
            self._stop_cam()
            self._set_cam_placeholder()

    def _restart_cam(self):
        self._stop_cam()
        if not self.cam_enabled.get():
            return
        if cv2 is None or ImageTk is None:
            self._set_cam_placeholder("Install opencv-python + pillow for preview.")
            return
        idx = int(self.cam_index.get())
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            self._set_cam_placeholder(f"Camera index {idx} not available.")
            cap.release()
            return
        self._cap = cap

    def _stop_cam(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None

    def _set_cam_placeholder(self, msg: str="No camera preview"):
        self.cam_label.configure(text=msg, image="")
        self._tk_cam_img = None

    def _update_cam_frame(self):
        if not self.cam_enabled.get() or self._cap is None:
            return
        ret, frame = self._cap.read()
        if not ret:
            return

        validated = self.rules.process_frame(frame)

        # v5: fire actions via rules.json
        action_lines = []
        # presence rising edge
        if validated.presence and (not self._presence_prev):
            action_lines += self.router.handle(key="presence", presence=validated.presence, sim_engine=self.engine, default_conf=max(0.0, min(1.0, validated.presence_score)))
        # plaque validated event
        if validated.plaque_id:
            action_lines += self.router.handle(key=f"PLAQUE:{validated.plaque_id}", presence=validated.presence, sim_engine=self.engine, default_conf=max(0.0, min(1.0, validated.plaque_score)))
        self._presence_prev = bool(validated.presence)
        if action_lines:
            self._action_log_lines += action_lines


        now = time.time()
        if self.trigger_mode.get() == "PRESENCE":
            if validated.presence and (now - self._last_injected_presence) > self._presence_inject_cooldown:
                self._last_injected_presence = now
                self.engine.inject_detection("presence", max(0.0, min(1.0, validated.presence_score)))
        else:
            if validated.plaque_id:
                self.engine.inject_detection(f"PLAQUE:{validated.plaque_id}", max(0.0, min(1.0, validated.plaque_score)))

        # annotate
        if cv2 is not None:
            txt1 = f"presence={validated.presence} score={validated.presence_score:.2f} ({self.rules.last_presence.detail})"
            txt2 = "plaque=none"
            if self.rules.last_plaque:
                txt2 = f"plaque_candidate={self.rules.last_plaque.plaque_id} score={self.rules.last_plaque.score:.2f} good={self.rules.last_plaque.good_matches}"
            cv2.putText(frame, txt1, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)
            cv2.putText(frame, txt2, (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)

        self.lbl_presence.configure(text=f"Presence: {validated.presence} (score={validated.presence_score:.3f}) mode={self.rules.presence.mode}")
        if self.rules.last_plaque:
            self.lbl_plaque.configure(text=f"Plaque candidate: {self.rules.last_plaque.plaque_id} score={self.rules.last_plaque.score:.2f} good={self.rules.last_plaque.good_matches}")
        else:
            self.lbl_plaque.configure(text="Plaque candidate: -")

        if ImageTk is None:
            return
        rgb = frame[:, :, ::-1]
        h, w = rgb.shape[:2]
        target_w = 560
        scale = target_w / max(1, w)
        new_w = target_w
        new_h = int(h * scale)
        try:
            rgb = cv2.resize(rgb, (new_w, new_h))
        except Exception:
            pass
        im = Image.fromarray(rgb)
        self._tk_cam_img = ImageTk.PhotoImage(image=im)
        self.cam_label.configure(image=self._tk_cam_img, text="")

    def _refresh_ui(self):
        snap = self.engine.snapshot()
        self.lbl_time.configure(text=f"t={snap['t']:.1f}s")
        fsm = snap["fsm"]
        self.lbl_fsm.configure(text=f"FSM: {fsm['state']} locked={fsm['locked_detection']}")
        ld = fsm.get("last_detection")
        self.lbl_last.configure(text=f"Last injected: {ld['label']} ({ld['conf']:.2f})" if ld else "Last injected: -")
        if hasattr(self, '_action_log_lines') and self._action_log_lines:
            self.lbl_actions.configure(text="Actions: " + " | ".join(self._action_log_lines[-2:]))
        else:
            self.lbl_actions.configure(text="Actions: -")
        pl = snap["player"]
        if pl["playing"]:
            self.lbl_player.configure(text=f"Player: {pl['name']}  remaining {pl['remaining_s']:.1f}s")
        else:
            self.lbl_player.configure(text="Player: stopped")

        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.insert(tk.END, snap["log_tail"])
        self.txt_log.configure(state="disabled")

    def _loop(self):
        if self.running:
            self.engine.step(float(self.dt.get()))
            self._refresh_ui()
        self._update_cam_frame()
        self.after(50, self._loop)

    def destroy(self):
        self._stop_cam()
        super().destroy()


def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
