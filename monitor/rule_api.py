"""
monitor/rule_api.py
Serveur FastAPI sur :8890
  GET  /           → GUI rule editor (HTML)
  GET  /rules      → retourne config/rules.yaml en JSON
  POST /rules      → sauvegarde les règles + reload auto
  POST /reload     → force reload du RuleEngine en cours
  GET  /status     → état courant du pipeline
  GET  /assets     → liste des fichiers assets (audio/img/video)
  POST /test_card  → injecte un event card_detected sur le WS
  POST /test_udp   → envoie un paquet UDP de test

Lancer: python monitor/rule_api.py
Accéder depuis le réseau: http://<ip_pi>:8890
"""
from __future__ import annotations
import time
import threading
from pathlib import Path

_HERE       = Path(__file__).parent
_ROOT       = _HERE.parent
RULES_PATH  = _ROOT / "config" / "rules.yaml"
ASSETS_PATH = _ROOT / "assets"

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import yaml
    _OK = True
except ImportError:
    _OK = False
    print("[rule_api] WARN: pip install fastapi uvicorn pyyaml")

_engine_ref = None   # injecté depuis main.py

app = FastAPI(title="S.T.E.A.M Rule Editor") if _OK else None

if _OK:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    # ── UI ────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def gui():
        html_path = _HERE / "rule_editor" / "index.html"
        return html_path.read_text(encoding="utf-8")

    # ── Rules CRUD ────────────────────────────────────────────────────
    @app.get("/rules")
    def get_rules():
        if not RULES_PATH.exists():
            return JSONResponse({"error": "rules.yaml introuvable"}, status_code=404)
        with open(RULES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return JSONResponse(data)

    @app.post("/rules")
    async def save_rules(request: Request):
        body = await request.json()
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            yaml.dump(body, f, allow_unicode=True, default_flow_style=False)
        if _engine_ref:
            _engine_ref.reload()
        return JSONResponse({"status": "ok"})

    @app.post("/reload")
    def reload_rules():
        if _engine_ref:
            _engine_ref.reload()
            return JSONResponse({"status": "reloaded",
                                 "rules": len(_engine_ref._rules)})
        return JSONResponse({"status": "no engine attached"})

    # ── Status ────────────────────────────────────────────────────────
    @app.get("/status")
    def get_status():
        rules_count = len(_engine_ref._rules) if _engine_ref else None
        return JSONResponse({
            "status":          "running",
            "engine_attached": _engine_ref is not None,
            "rules":           rules_count,
            "timestamp":       time.time(),
        })

    # ── Assets ───────────────────────────────────────────────────────
    @app.get("/assets")
    def list_assets():
        result = {}
        for cat in ("audio", "img", "video"):
            folder = ASSETS_PATH / cat
            result[cat] = (
                [str(p.relative_to(ASSETS_PATH / cat))
                 for p in folder.rglob("*")
                 if p.is_file() and not p.name.startswith(".")]
                if folder.exists() else []
            )
        return JSONResponse(result)

    # ── Test triggers ────────────────────────────────────────────────
    @app.post("/test_card")
    async def test_card(request: Request):
        """Injecte une fausse détection de carte sur le WebSocket monitor."""
        body    = await request.json()
        card_id = body.get("card_id", "plate_vampire")
        label   = card_id.replace("plate_", "").replace("_", " ").capitalize()
        from monitor.ws_bridge import push_event
        push_event({
            "type":    "card_detected",
            "card_id": card_id,
            "label":   label,
            "score":   0.99,
        })
        return JSONResponse({"status": "injected", "card_id": card_id})

    @app.post("/test_udp")
    async def test_udp(request: Request):
        """Envoie un paquet UDP de test vers Loxone (ou toute cible)."""
        body = await request.json()
        msg  = body.get("msg",  "STEAM_TEST")
        ip   = body.get("ip",   "192.168.1.50")
        port = body.get("port", 7777)
        try:
            from steamcore.udp import send_event
            send_event(msg, ip, port)
            return JSONResponse({"status": "sent", "msg": msg, "ip": ip, "port": port})
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


def start_in_thread(port: int = 8890, engine=None) -> threading.Thread | None:
    global _engine_ref
    _engine_ref = engine
    if not _OK:
        print("[rule_api] GUI désactivé (dépendances manquantes)")
        return None
    def run():
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    t = threading.Thread(target=run, daemon=True, name="rule-api")
    t.start()
    print(f"[rule_api] Rule editor  →  http://0.0.0.0:{port}")
    return t


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8890, reload=False)
