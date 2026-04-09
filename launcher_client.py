"""
launcher_client.py
STEAM Vision -- Client Control (tourne sur Salomon / Windows)
Pilote STYX a distance via l'API REST Flask.
"""
from __future__ import annotations
import threading, webbrowser, json
from urllib import request as urlrequest
import tkinter as tk
from tkinter import ttk

DEFAULT_IP   = "192.168.1."
DEFAULT_PORT = "5050"
POLL_MS      = 1000

DARK_BG  = "#1a1a2e"
PANEL_BG = "#16213e"
ACCENT   = "#0f3460"
GREEN    = "#00d4aa"
RED      = "#e94560"
ORANGE   = "#f5a623"
TEXT     = "#e0e0e0"
FONT     = ("Consolas", 10)
FONT_BIG = ("Consolas", 12, "bold")


class ClientLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STEAM Vision - Client Control")
        self.geometry("700x640")
        self.resizable(True, True)
        self.configure(bg=DARK_BG)
        self._connected  = False
        self._poll_job   = None
        self._base_url   = ""
        self._last_log   = []
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        hdr = tk.Frame(self, bg=ACCENT, pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="STEAM Vision  -  Client", bg=ACCENT,
                 fg=GREEN, font=("Consolas", 14, "bold")).pack(side=tk.LEFT, padx=16)
        self._lbl_conn = tk.Label(hdr, text="DISCONNECTED", bg=ACCENT,
                                  fg=RED, font=FONT_BIG)
        self._lbl_conn.pack(side=tk.RIGHT, padx=16)

        conn = tk.Frame(self, bg=PANEL_BG, pady=10, padx=14)
        conn.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(conn, text="STYX IP", bg=PANEL_BG, fg=TEXT,
                 font=FONT, width=10, anchor="w").grid(row=0, column=0, sticky="w")
        self._var_ip = tk.StringVar(value=DEFAULT_IP)
        tk.Entry(conn, textvariable=self._var_ip, bg="#333", fg=TEXT,
                 font=FONT, width=18, insertbackground=TEXT).grid(row=0, column=1, padx=6)
        tk.Label(conn, text="Port", bg=PANEL_BG, fg=TEXT,
                 font=FONT).grid(row=0, column=2, padx=6)
        self._var_port = tk.StringVar(value=DEFAULT_PORT)
        tk.Entry(conn, textvariable=self._var_port, bg="#333", fg=TEXT,
                 font=FONT, width=6, insertbackground=TEXT).grid(row=0, column=3, padx=4)
        self._btn_connect = tk.Button(conn, text="Connect", bg=GREEN,
                                      fg="#000", font=FONT, relief=tk.FLAT,
                                      command=self._toggle_connect)
        self._btn_connect.grid(row=0, column=4, padx=10)

        status_frame = tk.LabelFrame(self, text="  Status  ", bg=DARK_BG,
                                     fg=GREEN, font=FONT_BIG, pady=8, padx=14)
        status_frame.pack(fill=tk.X, padx=8, pady=4)
        self._vars_status = {}
        fields = [("FSM", "fsm"), ("Temps", "t"), ("Presence", "presence"),
                  ("Plaque", "plaque"), ("Config", "configfolder")]
        for i, (lbl, key) in enumerate(fields):
            tk.Label(status_frame, text=lbl + " :", bg=DARK_BG, fg=ORANGE,
                     font=FONT, width=12, anchor="w").grid(
                     row=i//2, column=(i % 2)*2, sticky="w", padx=6, pady=3)
            var = tk.StringVar(value="--")
            self._vars_status[key] = var
            tk.Label(status_frame, textvariable=var, bg=DARK_BG, fg=TEXT,
                     font=FONT, anchor="w", width=28).grid(
                     row=i//2, column=(i % 2)*2+1, sticky="w")

        act = tk.Frame(self, bg=PANEL_BG, pady=10, padx=14)
        act.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(act, text="Ouvrir stream dans navigateur",
                  bg=ACCENT, fg=TEXT, font=FONT, relief=tk.FLAT,
                  command=self._open_stream).pack(side=tk.LEFT, padx=4)
        tk.Button(act, text="Load config", bg=ACCENT, fg=TEXT,
                  font=FONT, relief=tk.FLAT,
                  command=self._show_load_config).pack(side=tk.LEFT, padx=4)

        inj = tk.LabelFrame(self, text="  Inject manuel  ", bg=DARK_BG,
                             fg=GREEN, font=FONT_BIG, pady=8, padx=14)
        inj.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(inj, text="Label", bg=DARK_BG, fg=TEXT,
                 font=FONT).pack(side=tk.LEFT)
        self._var_label = tk.StringVar(value="PLAQUE_bougie")
        tk.Entry(inj, textvariable=self._var_label, bg="#333", fg=TEXT,
                 font=FONT, width=20, insertbackground=TEXT).pack(side=tk.LEFT, padx=6)
        tk.Label(inj, text="Conf", bg=DARK_BG, fg=TEXT,
                 font=FONT).pack(side=tk.LEFT)
        self._var_conf = tk.StringVar(value="0.95")
        tk.Entry(inj, textvariable=self._var_conf, bg="#333", fg=TEXT,
                 font=FONT, width=6, insertbackground=TEXT).pack(side=tk.LEFT, padx=6)
        tk.Button(inj, text="Inject", bg=GREEN, fg="#000",
                  font=FONT, relief=tk.FLAT,
                  command=self._inject).pack(side=tk.LEFT, padx=8)

        log_frame = tk.Frame(self, bg=DARK_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        tk.Label(log_frame, text="Action log", bg=DARK_BG, fg=GREEN,
                 font=FONT_BIG).pack(anchor="w")
        txt_wrap = tk.Frame(log_frame, bg=DARK_BG)
        txt_wrap.pack(fill=tk.BOTH, expand=True)
        self._txt_log = tk.Text(txt_wrap, bg="#0d0d1a", fg=TEXT,
                                font=("Consolas", 9), wrap=tk.WORD,
                                state=tk.DISABLED, height=10)
        self._txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(txt_wrap, command=self._txt_log.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._txt_log.configure(yscrollcommand=sb.set)
        self._txt_log.tag_config("ok",   foreground=GREEN)
        self._txt_log.tag_config("err",  foreground=RED)
        self._txt_log.tag_config("info", foreground=ORANGE)

    def _toggle_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        ip   = self._var_ip.get().strip()
        port = self._var_port.get().strip() or DEFAULT_PORT
        self._base_url = "http://" + ip + ":" + port
        self._log("[client] Connexion vers " + self._base_url + " ...", "info")
        threading.Thread(target=self._check_connection, daemon=True).start()

    def _check_connection(self):
        try:
            data = self._get("api/status")
            self.after(0, self._on_connected, data)
        except Exception as e:
            self.after(0, self._on_connect_failed, str(e))

    def _on_connected(self, data):
        self._connected = True
        self._lbl_conn.configure(text="CONNECTED", fg=GREEN)
        self._btn_connect.configure(text="Disconnect", bg=RED, fg=TEXT)
        self._log("[client] Connecte !", "ok")
        self._update_status(data)
        self._schedule_poll()

    def _on_connect_failed(self, err):
        self._log("[client] ERREUR connexion : " + err, "err")

    def _disconnect(self):
        self._connected = False
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self._lbl_conn.configure(text="DISCONNECTED", fg=RED)
        self._btn_connect.configure(text="Connect", bg=GREEN, fg="#000")
        self._log("[client] Deconnecte", "info")
        for v in self._vars_status.values():
            v.set("--")

    def _schedule_poll(self):
        if not self._connected:
            return
        self._poll_job = self.after(POLL_MS, self._poll)

    def _poll(self):
        if not self._connected:
            return
        threading.Thread(target=self._do_poll, daemon=True).start()

    def _do_poll(self):
        try:
            data = self._get("api/status")
            self.after(0, self._update_status, data)
            self.after(0, self._schedule_poll)
        except Exception:
            self.after(0, self._on_poll_lost)

    def _on_poll_lost(self):
        self._log("[client] Connexion perdue", "err")
        self._disconnect()

    def _update_status(self, data):
        self._vars_status["fsm"].set(str(data.get("fsm", "--")))
        t = data.get("t", "--")
        self._vars_status["t"].set(str(t) + "s")
        presence = data.get("presence", False)
        score    = data.get("presencescore", 0)
        p_txt    = ("OUI" if presence else "NON") + "  (" + str(round(score, 2)) + ")"
        self._vars_status["presence"].set(p_txt)
        plaque  = data.get("plaque") or "none"
        pscore  = data.get("plaquescore", 0)
        pl_txt  = plaque + ("  (" + str(round(pscore, 2)) + ")" if plaque != "none" else "")
        self._vars_status["plaque"].set(pl_txt)
        self._vars_status["configfolder"].set(str(data.get("configfolder") or "--"))
        logs = data.get("actionlog", [])
        if logs and logs != self._last_log:
            new = logs[len(self._last_log):]
            if new:
                self._append_action_log(new)
            self._last_log = list(logs)

    def _append_action_log(self, lines):
        self._txt_log.configure(state=tk.NORMAL)
        nl = "\n"
        for line in lines:
            if "OK" in line or "sent" in line:
                tag = "ok"
            elif "ERROR" in line:
                tag = "err"
            else:
                tag = "info"
            self._txt_log.insert(tk.END, line + nl, tag)
        self._txt_log.see(tk.END)
        self._txt_log.configure(state=tk.DISABLED)

    def _open_stream(self):
        url = self._base_url if self._base_url else               "http://" + self._var_ip.get() + ":" + self._var_port.get()
        webbrowser.open(url)

    def _show_load_config(self):
        win = tk.Toplevel(self)
        win.title("Load config")
        win.configure(bg=DARK_BG)
        win.geometry("480x120")
        tk.Label(win, text="Dossier config (chemin STYX) :",
                 bg=DARK_BG, fg=TEXT, font=FONT).pack(anchor="w", padx=12, pady=8)
        var = tk.StringVar(value="/home/steam/steam_prop_vision/configs/")
        tk.Entry(win, textvariable=var, bg="#333", fg=TEXT,
                 font=FONT, width=52, insertbackground=TEXT).pack(padx=12)
        def send():
            self._load_config(var.get().strip())
            win.destroy()
        tk.Button(win, text="Envoyer", bg=GREEN, fg="#000",
                  font=FONT, relief=tk.FLAT, command=send).pack(pady=8)

    def _load_config(self, folder):
        threading.Thread(target=self._do_load_config,
                         args=(folder,), daemon=True).start()

    def _do_load_config(self, folder):
        try:
            data = json.dumps({"folder": folder}).encode()
            resp = self._post("api/config", data)
            self.after(0, self._log,
                       "[client] Config chargee : " + str(resp), "ok")
        except Exception as e:
            self.after(0, self._log,
                       "[client] Erreur load config : " + str(e), "err")

    def _inject(self):
        label = self._var_label.get().strip()
        try:
            conf = float(self._var_conf.get())
        except ValueError:
            conf = 0.9
        threading.Thread(target=self._do_inject,
                         args=(label, conf), daemon=True).start()

    def _do_inject(self, label, conf):
        try:
            data = json.dumps({"label": label, "conf": conf}).encode()
            resp = self._post("api/inject", data)
            self.after(0, self._log,
                       "[client] Inject " + label + " conf=" + str(conf) + " -> " + str(resp),
                       "ok")
        except Exception as e:
            self.after(0, self._log,
                       "[client] Erreur inject : " + str(e), "err")

    def _get(self, path):
        url = self._base_url + "/" + path
        with urlrequest.urlopen(url, timeout=3) as r:
            return json.loads(r.read())

    def _post(self, path, data):
        url = self._base_url + "/" + path
        req = urlrequest.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def _log(self, msg, tag=""):
        self._txt_log.configure(state=tk.NORMAL)
        end_char = "\n"
        if tag:
            self._txt_log.insert(tk.END, msg + end_char, tag)
        else:
            self._txt_log.insert(tk.END, msg + end_char)
        self._txt_log.see(tk.END)
        self._txt_log.configure(state=tk.DISABLED)

    def _on_close(self):
        self._disconnect()
        self.destroy()


if __name__ == "__main__":
    app = ClientLauncher()
    app.mainloop()
