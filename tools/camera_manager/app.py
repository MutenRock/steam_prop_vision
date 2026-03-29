# -*- coding: utf-8 -*-
"""
Camera Manager v2 — Import Imou/Dahua + test batch RTSP.
Peut être lancé seul ou depuis la main app via un bouton.
"""
from __future__ import annotations
import threading
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from .rtsp_scanner import scan_local_cameras, test_rtsp_source
from .profiles import RTSP_PROFILES, build_rtsp_url
from .cam_store import load_cameras, save_cameras
from .imou_importer import import_from_file, get_all_rtsp_candidates
from .batch_tester import test_camera_batch

PRESETS_FILE = os.path.join(os.path.dirname(__file__), "saved_cameras.json")

STATUS_COLORS = {
    "ok":          "#22c55e",
    "auth_failed": "#f59e0b",
    "no_rtsp":     "#ef4444",
    "timeout":     "#ef4444",
    "—":           "#9ca3af",
    "testing":     "#3b82f6",
}


class CameraManagerApp(tk.Toplevel):
    def __init__(self, master=None, on_select_callback=None):
        if master is None:
            self._root = tk.Tk()
            super().__init__(self._root)
            self._standalone = True
        else:
            super().__init__(master)
            self._root = None
            self._standalone = False

        self.on_select_callback = on_select_callback
        self.title("Camera Manager v2 — S.T.E.A.M Vision")
        self.geometry("1200x780")
        self.resizable(True, True)

        self._cap = None
        self._preview_active = False
        self._tk_img = None
        self._cameras: list[dict] = load_cameras(PRESETS_FILE)

        self._f_name     = tk.StringVar(value="Cam 1")
        self._f_source   = tk.StringVar(value="0")
        self._f_user     = tk.StringVar(value="admin")
        self._f_pass     = tk.StringVar(value="")
        self._f_ip       = tk.StringVar(value="192.168.1.")
        self._f_port     = tk.StringVar(value="554")
        self._f_profile  = tk.StringVar(value=list(RTSP_PROFILES.keys())[0])
        self._batch_user = tk.StringVar(value="admin")
        self._batch_pass = tk.StringVar(value="")

        self._build_ui()
        self._refresh_list()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Onglet 1 — Caméras
        tab_cams = ttk.Frame(nb)
        nb.add(tab_cams, text="📷  Caméras")
        self._build_tab_cameras(tab_cams)

        # Onglet 2 — Import
        tab_import = ttk.Frame(nb)
        nb.add(tab_import, text="📥  Import Imou/Dahua")
        self._build_tab_import(tab_import)

        # Onglet 3 — Test batch
        tab_batch = ttk.Frame(nb)
        nb.add(tab_batch, text="⚡  Test batch RTSP")
        self._build_tab_batch(tab_batch)

    # ── Onglet Caméras ────────────────────────────────────────────

    def _build_tab_cameras(self, parent):
        tb = ttk.Frame(parent)
        tb.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(tb, text="+ Manuel", command=self._add_manual).pack(side=tk.LEFT)
        ttk.Button(tb, text="🔍 Scanner locales", command=self._scan_local).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(tb, text="💾 Sauvegarder", command=self._save).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(tb, text="🗑 Supprimer", command=self._delete_selected).pack(side=tk.LEFT, padx=(6,0))
        if self.on_select_callback:
            ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
            ttk.Button(tb, text="✅ Utiliser cette caméra", command=self._use_selected).pack(side=tk.LEFT)

        paned = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        # Liste
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        lf = ttk.LabelFrame(left, text="Caméras configurées")
        lf.pack(fill=tk.BOTH, expand=True)
        cols = ("name", "source", "status")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name",   text="Nom")
        self.tree.heading("source", text="Source")
        self.tree.heading("status", text="Statut")
        self.tree.column("name",   width=130)
        self.tree.column("source", width=240)
        self.tree.column("status", width=90)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._stop_preview())

        # Form
        form = ttk.LabelFrame(left, text="Ajouter / Éditer")
        form.pack(fill=tk.X, pady=(8,0))

        ttk.Label(form, text="Nom :").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(form, textvariable=self._f_name, width=22).grid(row=0, column=1, columnspan=2, sticky="ew", padx=6)

        ttk.Label(form, text="Source directe :").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(form, textvariable=self._f_source, width=36).grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Label(form, text="index 0 ou rtsp://...").grid(row=1, column=3, sticky="w", padx=4)

        ttk.Separator(form, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=4, sticky="ew", pady=4)

        ttk.Label(form, text="Marque/profil :").grid(row=3, column=0, sticky="w", padx=6, pady=3)
        ttk.Combobox(form, textvariable=self._f_profile, values=list(RTSP_PROFILES.keys()),
                     state="readonly", width=22).grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(form, text="IP :").grid(row=4, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(form, textvariable=self._f_ip, width=18).grid(row=4, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Port RTSP :").grid(row=4, column=2, sticky="w", padx=4)
        ttk.Entry(form, textvariable=self._f_port, width=7).grid(row=4, column=3, sticky="w")

        ttk.Label(form, text="User :").grid(row=5, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(form, textvariable=self._f_user, width=14).grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Pass :").grid(row=5, column=2, sticky="w", padx=4)
        ttk.Entry(form, textvariable=self._f_pass, show="*", width=14).grid(row=5, column=3, sticky="w")

        row_btn = ttk.Frame(form)
        row_btn.grid(row=6, column=0, columnspan=4, sticky="w", padx=6, pady=6)
        ttk.Button(row_btn, text="⚙ Générer URL RTSP → Source",
                   command=self._generate_rtsp).pack(side=tk.LEFT)
        ttk.Button(row_btn, text="➕ Ajouter à la liste",
                   command=self._add_from_form).pack(side=tk.LEFT, padx=(8,0))
        form.columnconfigure(1, weight=1)

        # Preview
        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        ctrl = ttk.Frame(right)
        ctrl.pack(fill=tk.X)
        self.btn_preview = ttk.Button(ctrl, text="▶ Preview", command=self._toggle_preview)
        self.btn_preview.pack(side=tk.LEFT)
        ttk.Button(ctrl, text="⚡ Test rapide", command=self._quick_test).pack(side=tk.LEFT, padx=(6,0))
        self.lbl_status = ttk.Label(ctrl, text="Sélectionner une caméra", foreground="gray")
        self.lbl_status.pack(side=tk.LEFT, padx=12)

        pf = ttk.LabelFrame(right, text="Preview")
        pf.pack(fill=tk.BOTH, expand=True, pady=(6,0))
        self.lbl_preview = ttk.Label(pf, text="Aucun flux actif", anchor="center")
        self.lbl_preview.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        inf = ttk.LabelFrame(right, text="Infos flux")
        inf.pack(fill=tk.X, pady=(4,0))
        self.lbl_info = ttk.Label(inf, text="—")
        self.lbl_info.pack(anchor="w", padx=8, pady=4)

    # ── Onglet Import ─────────────────────────────────────────────

    def _build_tab_import(self, parent):
        frame = ttk.LabelFrame(parent, text="Import fichier export Imou / Dahua (.xlsx ou .csv)")
        frame.pack(fill=tk.X, padx=12, pady=12)

        ttk.Label(frame, text="Fichier export :").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self._import_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self._import_path, width=50).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frame, text="Parcourir…", command=self._browse_import).grid(row=0, column=2, padx=6)

        ttk.Label(frame, text="User caméras :").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=self._f_user, width=14).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(frame, text="(optionnel — laisser vide si pas encore configuré)").grid(
            row=1, column=2, sticky="w", padx=4, columnspan=2)

        ttk.Label(frame, text="Pass caméras :").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=self._f_pass, show="*", width=14).grid(row=2, column=1, sticky="w", padx=6)

        ttk.Button(frame, text="📥 Importer les caméras",
                   command=self._do_import).grid(row=3, column=1, sticky="w", padx=6, pady=8)
        frame.columnconfigure(1, weight=1)

        self._import_log = tk.Text(parent, height=14, state="disabled", wrap="word")
        self._import_log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,12))

    # ── Onglet Test batch ─────────────────────────────────────────

    def _build_tab_batch(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=12, pady=10)

        ttk.Label(top, text="User :").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self._batch_user, width=12).pack(side=tk.LEFT, padx=(4,12))
        ttk.Label(top, text="Pass :").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self._batch_pass, show="*", width=12).pack(side=tk.LEFT, padx=(4,12))

        self.btn_batch = ttk.Button(top, text="⚡ Tester toutes les caméras",
                                    command=self._start_batch_test)
        self.btn_batch.pack(side=tk.LEFT, padx=(12,0))
        self.lbl_batch_status = ttk.Label(top, text="", foreground="gray")
        self.lbl_batch_status.pack(side=tk.LEFT, padx=12)

        # Résultats
        cols = ("name", "source", "result", "working_url")
        self.batch_tree = ttk.Treeview(parent, columns=cols, show="headings")
        self.batch_tree.heading("name",        text="Nom")
        self.batch_tree.heading("source",      text="Source initiale")
        self.batch_tree.heading("result",      text="Résultat")
        self.batch_tree.heading("working_url", text="URL fonctionnelle")
        self.batch_tree.column("name",        width=130)
        self.batch_tree.column("source",      width=230)
        self.batch_tree.column("result",      width=100)
        self.batch_tree.column("working_url", width=310)
        self.batch_tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,6))

        bb = ttk.Frame(parent)
        bb.pack(fill=tk.X, padx=12, pady=(0,10))
        ttk.Button(bb, text="✅ Appliquer les URLs fonctionnelles aux caméras",
                   command=self._apply_batch_results).pack(side=tk.LEFT)
        ttk.Button(bb, text="💾 Sauvegarder",
                   command=self._save).pack(side=tk.LEFT, padx=(8,0))

        self._batch_results: dict[str, tuple[str,str]] = {}  # cam_id → (status, working_url)

    # ── Logique Caméras ───────────────────────────────────────────

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for cam in self._cameras:
            status = cam.get("status", "—")
            self.tree.insert("", tk.END, iid=cam["id"],
                             values=(cam["name"], cam["source"], status))

    def _get_selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        return next((c for c in self._cameras if c["id"] == iid), None)

    def _generate_rtsp(self):
        url = build_rtsp_url(
            profile=self._f_profile.get(),
            ip=self._f_ip.get().strip(),
            port=self._f_port.get().strip(),
            user=self._f_user.get().strip(),
            password=self._f_pass.get().strip(),
        )
        self._f_source.set(url)

    def _add_from_form(self):
        source = self._f_source.get().strip()
        name = self._f_name.get().strip() or source
        if not source:
            messagebox.showwarning("Source vide", "Renseigne une source.")
            return
        import uuid
        cam = {"id": str(uuid.uuid4())[:8], "name": name, "source": source, "status": "—"}
        self._cameras.append(cam)
        self._refresh_list()

    def _add_manual(self):
        self._f_name.set(f"Cam {len(self._cameras)+1}")
        self._f_source.set("")

    def _delete_selected(self):
        cam = self._get_selected()
        if not cam:
            return
        self._cameras = [c for c in self._cameras if c["id"] != cam["id"]]
        self._stop_preview()
        self._refresh_list()

    def _scan_local(self):
        self.lbl_status.configure(text="Scan caméras locales...", foreground="orange")
        self.update()

        def _run():
            found = scan_local_cameras(max_index=6)
            for idx, w, h in found:
                import uuid
                cam = {
                    "id": str(uuid.uuid4())[:8],
                    "name": f"Locale index {idx}",
                    "source": str(idx),
                    "status": f"OK {w}x{h}"
                }
                if not any(c["source"] == str(idx) for c in self._cameras):
                    self._cameras.append(cam)
            self.after(0, lambda: (
                self._refresh_list(),
                self.lbl_status.configure(
                    text=f"{len(found)} caméra(s) locale(s) trouvée(s)",
                    foreground="green" if found else "red"
                )
            ))

        threading.Thread(target=_run, daemon=True).start()

    def _quick_test(self):
        cam = self._get_selected()
        if not cam:
            messagebox.showinfo("Sélection", "Sélectionne une caméra dans la liste.")
            return
        self.lbl_status.configure(text="Test en cours...", foreground="orange")
        self.update()

        def _run():
            ok, msg = test_rtsp_source(cam["source"])
            cam["status"] = "✅ OK" if ok else "❌ KO"
            self.after(0, lambda: (
                self._refresh_list(),
                self.lbl_status.configure(text=msg, foreground="green" if ok else "red")
            ))

        threading.Thread(target=_run, daemon=True).start()

    def _use_selected(self):
        cam = self._get_selected()
        if not cam:
            messagebox.showinfo("Sélection", "Sélectionne une caméra.")
            return
        if self.on_select_callback:
            self.on_select_callback(cam["source"], cam["name"])
        self._on_close()

    def _save(self):
        save_cameras(PRESETS_FILE, self._cameras)
        self.lbl_status.configure(text="💾 Sauvegardé", foreground="green")

    # ── Preview ───────────────────────────────────────────────────

    def _toggle_preview(self):
        if self._preview_active:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        cam = self._get_selected()
        if not cam:
            messagebox.showinfo("Sélection", "Sélectionne une caméra.")
            return
        if cv2 is None:
            messagebox.showerror("OpenCV manquant", "opencv-python requis.")
            return
        source = cam["source"]
        cap_source = int(source) if source.strip().isdigit() else source
        self._cap = cv2.VideoCapture(cap_source, cv2.CAP_FFMPEG)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self._cap.isOpened():
            self.lbl_status.configure(text="❌ Source non disponible", foreground="red")
            self._cap = None
            return
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.lbl_info.configure(text=f"{w}x{h} | {fps:.1f} FPS | {source}")
        cam["status"] = "✅ OK"
        self._refresh_list()
        self._preview_active = True
        self.btn_preview.configure(text="⏹ Arrêter")
        self._preview_loop()

    def _preview_loop(self):
        if not self._preview_active or self._cap is None:
            return
        ret, frame = self._cap.read()
        if ret and frame is not None and ImageTk is not None:
            h, w = frame.shape[:2]
            target_w = 600
            frame = cv2.resize(frame, (target_w, int(h * target_w / max(1, w))))
            rgb = frame[:, :, ::-1]
            im = Image.fromarray(rgb)
            self._tk_img = ImageTk.PhotoImage(image=im)
            self.lbl_preview.configure(image=self._tk_img, text="")
        elif not ret:
            self._stop_preview()
            self.lbl_status.configure(text="⚠ Flux interrompu", foreground="orange")
            return
        self.after(33, self._preview_loop)

    def _stop_preview(self):
        self._preview_active = False
        self.btn_preview.configure(text="▶ Preview")
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.lbl_preview.configure(image="", text="Aucun flux actif")
        self._tk_img = None

    # ── Import ────────────────────────────────────────────────────

    def _browse_import(self):
        path = filedialog.askopenfilename(
            title="Sélectionner l'export Imou/Dahua",
            filetypes=[("Excel/CSV", "*.xlsx *.csv"), ("Tous", "*.*")]
        )
        if path:
            self._import_path.set(path)

    def _do_import(self):
        path = self._import_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Fichier introuvable", f"Fichier non trouvé : {path}")
            return
        user = self._f_user.get().strip()
        password = self._f_pass.get().strip()
        try:
            imported = import_from_file(path, user=user, password=password)
        except Exception as e:
            messagebox.showerror("Erreur import", str(e))
            return

        added = 0
        for cam in imported:
            existing_ips = [c.get("meta", {}).get("ip") for c in self._cameras]
            meta_ip = cam.get("meta", {}).get("ip")
            if meta_ip and meta_ip in existing_ips:
                continue  # déjà présente
            self._cameras.append(cam)
            added += 1

        self._refresh_list()
        self._import_log.configure(state="normal")
        self._import_log.delete("1.0", tk.END)
        self._import_log.insert(tk.END,
            f"Import terminé : {added} caméra(s) ajoutée(s) / {len(imported)} trouvées.

"
        )
        for cam in imported:
            meta = cam.get("meta", {})
            self._import_log.insert(tk.END,
                f"  ✔ {meta.get('model','?')} — {meta.get('ip','?')}  MAC:{meta.get('mac','?')}
"
                f"     Source RTSP par défaut : {cam['source']}

"
            )
        self._import_log.configure(state="disabled")

    # ── Batch test ────────────────────────────────────────────────

    def _start_batch_test(self):
        if not self._cameras:
            messagebox.showinfo("Vide", "Aucune caméra à tester. Ajoutez-en d'abord.")
            return
        self.btn_batch.configure(state="disabled")
        self.lbl_batch_status.configure(text="Tests en cours…", foreground="orange")
        self.batch_tree.delete(*self.batch_tree.get_children())
        self._batch_results = {}

        # Pré-remplir les lignes
        for cam in self._cameras:
            self.batch_tree.insert("", tk.END, iid=cam["id"],
                                   values=(cam["name"], cam["source"], "…", ""))

        user = self._batch_user.get().strip()
        password = self._batch_pass.get().strip()

        def _on_result(cam_id: str, status: str, working_url: str):
            self._batch_results[cam_id] = (status, working_url)
            label = {"ok": "✅ OK", "auth_failed": "⚠ Auth KO",
                     "no_rtsp": "❌ KO", "timeout": "⏱ Timeout"}.get(status, status)
            self.after(0, lambda: self.batch_tree.item(
                cam_id, values=(
                    self.batch_tree.set(cam_id, "name"),
                    self.batch_tree.set(cam_id, "source"),
                    label,
                    working_url if status == "ok" else ""
                )
            ))

        def _on_done():
            ok_count = sum(1 for s, _ in self._batch_results.values() if s == "ok")
            total = len(self._batch_results)
            self.after(0, lambda: (
                self.btn_batch.configure(state="normal"),
                self.lbl_batch_status.configure(
                    text=f"{ok_count}/{total} caméra(s) OK",
                    foreground="green" if ok_count > 0 else "red"
                )
            ))

        test_camera_batch(self._cameras, user, password, _on_result, _on_done)

    def _apply_batch_results(self):
        applied = 0
        for cam in self._cameras:
            result = self._batch_results.get(cam["id"])
            if result and result[0] == "ok":
                cam["source"] = result[1]
                cam["status"] = "✅ OK"
                applied += 1
        self._refresh_list()
        self.lbl_batch_status.configure(
            text=f"{applied} URL(s) appliquée(s)", foreground="green"
        )

    # ── Close ─────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_preview()
        self.destroy()
        if self._standalone and self._root:
            self._root.destroy()

    def run_standalone(self):
        if self._standalone and self._root:
            self._root.mainloop()


def main():
    app = CameraManagerApp(master=None)
    app.run_standalone()


if __name__ == "__main__":
    main()
