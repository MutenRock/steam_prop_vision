"""
launcher_server.py
STEAM Vision -- Server Launcher (tourne sur STYX)
Lance scripts/linux_run.sh et affiche les logs en temps reel.
"""
from __future__ import annotations
import os, subprocess, threading, signal
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

BASE_DIR     = Path(__file__).parent
SCRIPT_RUN   = BASE_DIR / "scripts" / "linux_run.sh"
CONFIGS_DIR  = BASE_DIR / "configs"
DEFAULT_PORT = "5050"

DARK_BG  = "#1a1a2e"
PANEL_BG = "#16213e"
ACCENT   = "#0f3460"
GREEN    = "#00d4aa"
RED      = "#e94560"
TEXT     = "#e0e0e0"
FONT     = ("Consolas", 10)
FONT_BIG = ("Consolas", 12, "bold")


def list_configs() -> list:
    if not CONFIGS_DIR.exists():
        return []
    return sorted(d.name for d in CONFIGS_DIR.iterdir() if d.is_dir())


class ServerLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STEAM Vision - Server Launcher")
        self.geometry("820x620")
        self.resizable(True, True)
        self.configure(bg=DARK_BG)
        self._proc = None
        self._running = False
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        hdr = tk.Frame(self, bg=ACCENT, pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="STEAM Vision  -  Server", bg=ACCENT,
                 fg=GREEN, font=("Consolas", 14, "bold")).pack(side=tk.LEFT, padx=16)
        self._lbl_status = tk.Label(hdr, text="STOPPED", bg=ACCENT,
                                    fg=RED, font=FONT_BIG)
        self._lbl_status.pack(side=tk.RIGHT, padx=16)

        cfg = tk.Frame(self, bg=PANEL_BG, pady=10, padx=14)
        cfg.pack(fill=tk.X, padx=8, pady=6)

        tk.Label(cfg, text="Config", bg=PANEL_BG, fg=TEXT,
                 font=FONT, width=10, anchor="w").grid(row=0, column=0, sticky="w")
        self._var_config = tk.StringVar()
        configs = list_configs()
        self._cmb_config = ttk.Combobox(cfg, textvariable=self._var_config,
                                         values=configs, width=28, state="readonly")
        if configs:
            self._cmb_config.set(configs[0])
        self._cmb_config.grid(row=0, column=1, padx=6)
        tk.Button(cfg, text="Browse", bg=ACCENT, fg=TEXT, font=FONT,
                  relief=tk.FLAT, command=self._browse_config).grid(row=0, column=2, padx=4)

        tk.Label(cfg, text="Port", bg=PANEL_BG, fg=TEXT,
                 font=FONT, width=10, anchor="w").grid(row=1, column=0, sticky="w", pady=4)
        self._var_port = tk.StringVar(value=DEFAULT_PORT)
        tk.Entry(cfg, textvariable=self._var_port, bg="#333", fg=TEXT,
                 font=FONT, width=8, insertbackground=TEXT).grid(row=1, column=1, sticky="w", padx=6)

        tk.Label(cfg, text="Mode", bg=PANEL_BG, fg=TEXT,
                 font=FONT, width=10, anchor="w").grid(row=2, column=0, sticky="w")
        self._var_mode = tk.StringVar(value="plaque")
        for i, mode in enumerate(["plaque", "presence", "yolo"]):
            tk.Radiobutton(cfg, text=mode, variable=self._var_mode, value=mode,
                           bg=PANEL_BG, fg=TEXT, selectcolor=ACCENT,
                           activebackground=PANEL_BG, font=FONT).grid(
                           row=2, column=i+1, padx=6, sticky="w")

        btn_frame = tk.Frame(self, bg=DARK_BG)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        self._btn_start = tk.Button(btn_frame, text="START", bg=GREEN,
                                    fg="#000", font=FONT_BIG, width=14,
                                    relief=tk.FLAT, command=self._start)
        self._btn_start.pack(side=tk.LEFT, padx=6)
        self._btn_stop = tk.Button(btn_frame, text="STOP", bg=RED,
                                   fg=TEXT, font=FONT_BIG, width=14,
                                   relief=tk.FLAT, state=tk.DISABLED,
                                   command=self._stop)
        self._btn_stop.pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="Reload configs", bg=ACCENT, fg=TEXT,
                  font=FONT, relief=tk.FLAT,
                  command=self._reload_configs).pack(side=tk.LEFT, padx=12)
        tk.Button(btn_frame, text="Clear logs", bg=ACCENT, fg=TEXT,
                  font=FONT, relief=tk.FLAT,
                  command=self._clear_logs).pack(side=tk.RIGHT, padx=6)

        log_frame = tk.Frame(self, bg=DARK_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        tk.Label(log_frame, text="Logs", bg=DARK_BG, fg=GREEN,
                 font=FONT_BIG).pack(anchor="w")
        txt_wrap = tk.Frame(log_frame, bg=DARK_BG)
        txt_wrap.pack(fill=tk.BOTH, expand=True)
        self._txt_log = tk.Text(txt_wrap, bg="#0d0d1a", fg=TEXT,
                                font=("Consolas", 9), wrap=tk.WORD,
                                state=tk.DISABLED, insertbackground=TEXT)
        self._txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(txt_wrap, command=self._txt_log.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._txt_log.configure(yscrollcommand=sb.set)
        self._txt_log.tag_config("ok",   foreground=GREEN)
        self._txt_log.tag_config("err",  foreground=RED)
        self._txt_log.tag_config("info", foreground="#aaaaff")

    def _browse_config(self):
        folder = filedialog.askdirectory(title="Choisir un dossier config",
                                         initialdir=str(CONFIGS_DIR))
        if folder:
            self._var_config.set(Path(folder).name)

    def _reload_configs(self):
        configs = list_configs()
        self._cmb_config["values"] = configs
        self._log("[launcher] configs rechargees : " + str(len(configs)), "info")

    def _start(self):
        if self._running:
            return
        config = self._var_config.get().strip()
        port   = self._var_port.get().strip() or DEFAULT_PORT
        mode   = self._var_mode.get()
        if not SCRIPT_RUN.exists():
            self._log("[launcher] ERREUR : " + str(SCRIPT_RUN) + " introuvable", "err")
            return
        env = os.environ.copy()
        env["STEAM_CONFIG"] = str(CONFIGS_DIR / config) if config else ""
        env["STEAM_PORT"]   = port
        env["STEAM_MODE"]   = mode
        self._log("[launcher] START config=" + config + " port=" + port + " mode=" + mode, "ok")
        try:
            self._proc = subprocess.Popen(
                ["bash", str(SCRIPT_RUN)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._log("[launcher] Impossible de lancer le script : " + str(e), "err")
            return
        self._running = True
        self._btn_start.configure(state=tk.DISABLED)
        self._btn_stop.configure(state=tk.NORMAL)
        self._lbl_status.configure(text="RUNNING", fg=GREEN)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._watch_proc,  daemon=True).start()

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            self._log("[launcher] STOP envoye (SIGTERM)", "err")

    def _read_stdout(self):
        if not self._proc:
            return
        for line in self._proc.stdout:
            line = line.rstrip()
            if any(w in line for w in ("OK", "loaded", "Ready", "started")):
                tag = "ok"
            elif any(w in line for w in ("ERROR", "ERREUR", "Traceback", "Error")):
                tag = "err"
            elif line.startswith("["):
                tag = "info"
            else:
                tag = ""
            self.after(0, self._log, line, tag)

    def _watch_proc(self):
        if not self._proc:
            return
        self._proc.wait()
        code = self._proc.returncode
        self.after(0, self._on_proc_ended, code)

    def _on_proc_ended(self, code):
        self._running = False
        self._proc    = None
        self._btn_start.configure(state=tk.NORMAL)
        self._btn_stop.configure(state=tk.DISABLED)
        self._lbl_status.configure(text="STOPPED", fg=RED)
        tag = "ok" if code == 0 else "err"
        self._log("[launcher] process termine (code " + str(code) + ")", tag)

    def _log(self, msg, tag=""):
        self._txt_log.configure(state=tk.NORMAL)
        end_char = "\n"
        if tag:
            self._txt_log.insert(tk.END, msg + end_char, tag)
        else:
            self._txt_log.insert(tk.END, msg + end_char)
        self._txt_log.see(tk.END)
        self._txt_log.configure(state=tk.DISABLED)

    def _clear_logs(self):
        self._txt_log.configure(state=tk.NORMAL)
        self._txt_log.delete("1.0", tk.END)
        self._txt_log.configure(state=tk.DISABLED)

    def _on_close(self):
        self._stop()
        self.destroy()


if __name__ == "__main__":
    app = ServerLauncher()
    app.mainloop()
