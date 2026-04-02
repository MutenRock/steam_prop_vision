"""
monitor/rule_api.py
Serveur FastAPI sur :8890
  GET  /           → GUI rule editor (HTML)
  GET  /rules      → retourne config/rules.yaml en JSON
  POST /rules      → sauvegarde les règles
  POST /reload     → force reload du RuleEngine en cours

Lancer: python monitor/rule_api.py
Accéder depuis Salomon: http://192.168.1.136:8890
"""
from __future__ import annotations
import threading
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import yaml
    _OK = True
except ImportError:
    _OK = False
    print("[rule_api] WARN: pip install fastapi uvicorn pyyaml")

RULES_PATH = Path("config/rules.yaml")
_engine_ref = None  # injecté depuis main.py si besoin

app = FastAPI(title="S.T.E.A.M Rule Editor") if _OK else None

if _OK:
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/", response_class=HTMLResponse)
    def gui():
        html_path = Path(__file__).parent / "rule_editor" / "index.html"
        return html_path.read_text(encoding="utf-8")

    @app.get("/rules")
    def get_rules():
        if not RULES_PATH.exists():
            return JSONResponse({"error": "rules.yaml introuvable"}, status_code=404)
        with open(RULES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return JSONResponse(data)

    @app.post("/rules")
    async def save_rules(request):
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
            return JSONResponse({"status": "reloaded"})
        return JSONResponse({"status": "no engine attached"})

    @app.get("/assets")
    def list_assets():
        result = {}
        for cat in ("audio", "img", "video"):
            folder = Path(f"assets/{cat}")
            result[cat] = [str(p.relative_to("assets")) for p in folder.rglob("*") if p.is_file()] if folder.exists() else []
        return JSONResponse(result)


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
    print(f"[rule_api] GUI disponible sur http://0.0.0.0:{port}")
    return t


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8890, reload=False)
