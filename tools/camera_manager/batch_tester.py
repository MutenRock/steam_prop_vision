# -*- coding: utf-8 -*-
"""
Test batch de flux RTSP sur une liste de caméras.
Résultats : OK / auth_failed / no_rtsp / timeout
"""
from __future__ import annotations
import threading
from typing import Callable, List

from .rtsp_scanner import test_rtsp_source
from .imou_importer import get_all_rtsp_candidates


def _classify_error(source: str) -> str:
    """Tente d'identifier la cause d'échec."""
    src_lower = source.lower()
    if "401" in src_lower or "403" in src_lower:
        return "auth_failed"
    return "no_rtsp"


def test_camera_batch(
    cameras: List[dict],
    user: str,
    password: str,
    on_result: Callable[[str, str, str], None],  # (cam_id, status, source_ok)
    on_done: Callable[[], None],
) -> None:
    """
    Lance les tests en thread daemon.
    Pour chaque caméra :
      - Essaie toutes les URLs RTSP candidates
      - Appelle on_result(cam_id, status, working_source) dès qu'un résultat est connu
      - status : "ok" | "auth_failed" | "no_rtsp" | "timeout"
    """

    def _run():
        for cam in cameras:
            cam_id = cam["id"]
            meta = cam.get("meta", {})
            source = cam["source"]

            # Si la caméra a des métadonnées Imou → tester tous les profils
            if meta.get("brand") == "Imou" and meta.get("ip"):
                candidates = get_all_rtsp_candidates(meta, user, password)
            else:
                candidates = [source]

            found = False
            for candidate in candidates:
                ok, msg = test_rtsp_source(candidate, timeout_s=5.0)
                if ok:
                    on_result(cam_id, "ok", candidate)
                    found = True
                    break

            if not found:
                on_result(cam_id, "no_rtsp", source)

        on_done()

    threading.Thread(target=_run, daemon=True).start()
