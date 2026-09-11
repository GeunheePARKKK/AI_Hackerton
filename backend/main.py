"""AI Ship Design Debugger - backend entrypoint.

Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.detector import inspect_scene
from backend.llm import explain_violation
from backend.models import Scene
from backend.resolver import apply_action, resolve_violation

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DATA_FILE = BASE_DIR / "data" / "engine_room.json"

app = FastAPI(title="AI Ship Design Debugger")


def load_scene() -> Scene:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return Scene.model_validate(raw)


# Working copy: candidate fixes are applied here (original file is never touched)
WORK: dict[str, Scene] = {"scene": load_scene()}


@app.get("/api/scene")
def get_scene() -> Scene:
    """Return the current design scene (equipment, structures, pipes)."""
    return WORK["scene"]


@app.get("/api/inspect")
def inspect() -> dict:
    """Run the deterministic rule engine and return all violations."""
    return inspect_scene(WORK["scene"])


@app.get("/api/resolve/{violation_id}")
def resolve(violation_id: str) -> dict:
    """Generate verified fix candidates for one violation."""
    return resolve_violation(WORK["scene"], violation_id)


@app.get("/api/explain/{violation_id}")
def explain(violation_id: str) -> dict:
    """LLM explanation of a violation, grounded in verified engine output."""
    res = resolve_violation(WORK["scene"], violation_id)
    if "error" in res:
        return res
    analysis = explain_violation(res["violation"], res["candidates"])
    return {"violation": res["violation"], "candidates": res["candidates"],
            "analysis": analysis}


@app.post("/api/apply")
def apply_fix(action: dict = Body(...)) -> dict:
    """Apply a fix candidate to the working scene and re-inspect."""
    WORK["scene"] = apply_action(WORK["scene"], action)
    return inspect_scene(WORK["scene"])


@app.post("/api/reset")
def reset() -> dict:
    """Discard all applied fixes and reload the original design."""
    WORK["scene"] = load_scene()
    return inspect_scene(WORK["scene"])


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
