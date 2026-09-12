"""AI Ship Design Debugger - backend entrypoint.

Run:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.commands import run_command
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
UNDO: list[Scene] = []
REDO: list[Scene] = []


def _mutate(new_scene: Scene) -> None:
    UNDO.append(WORK["scene"])
    if len(UNDO) > 50:
        UNDO.pop(0)
    REDO.clear()
    WORK["scene"] = new_scene


@app.get("/api/scene")
def get_scene() -> Scene:
    """Return the current design scene (equipment, structures, pipes)."""
    return WORK["scene"]


@app.put("/api/scene")
def update_scene(scene: Scene) -> dict:
    """Replace the working scene (interactive editing) and re-inspect."""
    _mutate(scene)
    return inspect_scene(scene)


@app.post("/api/save")
def save_scene() -> dict:
    """Persist the working scene to the design file."""
    DATA_FILE.write_text(
        json.dumps(WORK["scene"].model_dump(by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"saved": True}


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
    _mutate(apply_action(WORK["scene"], action))
    return inspect_scene(WORK["scene"])


@app.post("/api/undo")
def undo() -> dict:
    if UNDO:
        REDO.append(WORK["scene"])
        WORK["scene"] = UNDO.pop()
    return inspect_scene(WORK["scene"])


@app.post("/api/redo")
def redo() -> dict:
    if REDO:
        UNDO.append(WORK["scene"])
        WORK["scene"] = REDO.pop()
    return inspect_scene(WORK["scene"])


@app.post("/api/autofix")
def autofix() -> dict:
    """Agent loop: fix violations one by one (HIGH first), re-verifying each step."""
    scene = WORK["scene"]
    steps: list[dict] = []
    skipped: set[tuple] = set()

    def key(v: dict) -> tuple:
        return (*sorted([v["a"]["id"], v["b"]["id"]]), v["code"])

    for _ in range(20):
        pending = [v for v in inspect_scene(scene)["violations"] if key(v) not in skipped]
        if not pending:
            break
        pending.sort(key=lambda v: 0 if v["severity"] == "HIGH" else 1)
        v = pending[0]
        cands = resolve_violation(scene, v["id"]).get("candidates") or []
        clean = [c for c in cands if c["verified"]]
        pick = (clean or cands)[0] if cands else None
        if pick is None:
            skipped.add(key(v))
            steps.append({"violation": f"{v['a']['id']} ↔ {v['b']['id']} ({v['code']})",
                          "action": None, "verified": False})
            continue
        scene = apply_action(scene, pick["action"])
        steps.append({"violation": f"{v['a']['id']} ↔ {v['b']['id']} ({v['code']})",
                      "action": pick["description"], "verified": pick["verified"]})

    if any(s["action"] for s in steps):
        _mutate(scene)
    return {"steps": steps, "inspection": inspect_scene(WORK["scene"])}


@app.post("/api/command")
def command(body: dict = Body(...)) -> dict:
    """Natural-language design command via LLM -> structured ops -> re-inspect."""
    result = run_command(WORK["scene"], str(body.get("text", ""))[:500])
    if result.get("scene") is not None:
        _mutate(result.pop("scene"))
    else:
        result.pop("scene", None)
    result["inspection"] = inspect_scene(WORK["scene"])
    return result


@app.post("/api/reset")
def reset() -> dict:
    """Discard all applied fixes and reload the original design."""
    UNDO.clear()
    REDO.clear()
    WORK["scene"] = load_scene()
    return inspect_scene(WORK["scene"])


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
