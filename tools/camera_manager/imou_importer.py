# -*- coding: utf-8 -*-
"""
Import d'exports Imou/Dahua (.xlsx ou .csv) vers une liste de caméras candidates.
Colonnes attendues : *IP, *Port, Model, MAC, Serial No.
"""
from __future__ import annotations
import os
import uuid
from typing import List

RTSP_PORT = 554  # Port RTSP standard Imou (distinct du port service 37777)

IMOU_RTSP_PROFILES = [
    "rtsp://{user}:{password}@{ip}:{rtsp_port}/cam/realmonitor?channel=1&subtype=0",
    "rtsp://{user}:{password}@{ip}:{rtsp_port}/cam/realmonitor?channel=1&subtype=1",
    "rtsp://{user}:{password}@{ip}:{rtsp_port}/live/main",
    "rtsp://{user}:{password}@{ip}:{rtsp_port}/live/sub",
]


def import_from_file(path: str, user: str = "admin", password: str = "") -> List[dict]:
    """
    Lit un .xlsx ou .csv exporté depuis l'outil Imou/Dahua.
    Retourne une liste de dicts caméra compatibles avec cam_store.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return _from_xlsx(path, user, password)
    elif ext == ".csv":
        return _from_csv(path, user, password)
    raise ValueError(f"Format non supporté : {ext}. Utilisez .xlsx ou .csv")


def _parse_rows(rows: list[dict], user: str, password: str) -> List[dict]:
    cameras = []
    for row in rows:
        ip = str(row.get("*IP") or row.get("IP") or "").strip()
        if not ip:
            continue
        model = str(row.get("Model") or row.get("Type") or "IPC").strip()
        mac = str(row.get("MAC") or "").strip()
        serial = str(row.get("Serial No.") or "").strip()
        service_port = str(row.get("*Port") or row.get("Port") or "37777").strip()

        name = f"{model} — {ip}"
        # Source par défaut : premier profil RTSP Imou
        source = IMOU_RTSP_PROFILES[0].format(
            user=user, password=password, ip=ip, rtsp_port=RTSP_PORT
        )

        cam = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "source": source,
            "status": "—",
            "meta": {
                "ip": ip,
                "model": model,
                "mac": mac,
                "serial": serial,
                "service_port": service_port,
                "brand": "Imou",
                "rtsp_port": RTSP_PORT,
                "user": user,
            }
        }
        cameras.append(cam)
    return cameras


def _from_xlsx(path: str, user: str, password: str) -> List[dict]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl requis : pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h else "" for h in next(rows_iter)]
    rows = []
    for row in rows_iter:
        rows.append(dict(zip(headers, row)))
    wb.close()
    return _parse_rows(rows, user, password)


def _from_csv(path: str, user: str, password: str) -> List[dict]:
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return _parse_rows(rows, user, password)


def get_all_rtsp_candidates(cam_meta: dict, user: str, password: str) -> List[str]:
    """Retourne toutes les URL RTSP candidates pour une caméra."""
    ip = cam_meta.get("ip", "")
    rtsp_port = cam_meta.get("rtsp_port", RTSP_PORT)
    return [
        p.format(user=user, password=password, ip=ip, rtsp_port=rtsp_port)
        for p in IMOU_RTSP_PROFILES
    ]
