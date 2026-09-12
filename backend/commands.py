"""Natural-language design commands (LLM copilot mode).

The LLM translates a Korean request into a list of structured ops;
all geometry mutation is done here in plain Python, then the rule
engine re-inspects. The LLM never edits the scene directly.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from backend.llm import _call_claude
from backend.models import Box, Equipment, Pipe, Scene, Structure

TYPE_SIZES = {
    "pump": [1, 1, 1.2], "heat_exchanger": [2.5, 2, 2], "generator": [3, 2, 2],
    "tank": [2, 2, 2.5], "engine": [6, 4, 4],
}

PROMPT = """당신은 조선 설계 3D CAD 어시스턴트입니다. 현재 기관실 설계 상태(단위: 미터, Z-up, 장비는 바닥 z=0에 놓임):
{scene}

사용자 요청: "{text}"

사용 가능한 작업(ops) 목록:
- {{"op":"add_equipment","type":"pump|heat_exchanger|generator|tank|engine","center":[x,y]}}
- {{"op":"add_frame","x":<x위치>}}
- {{"op":"move","id":"<객체id>","delta":[dx,dy,dz]}}
- {{"op":"delete","id":"<객체id>"}}
- {{"op":"add_pipe","diameter_mm":80,"path":[[x,y,z],[x,y,z],...]}}
- {{"op":"set_diameter","id":"P-xxx","diameter_mm":100}}

규칙:
- 반드시 방(room) 경계 안에 배치하고, 기존 객체의 box와 겹치지 않도록 좌표를 계산할 것
- 배관 경로는 축에 평행한 직교 구간으로 구성 (경유점 2개 이상)
- 존재하는 id만 참조할 것
- 요청이 모호하면 합리적으로 해석할 것

순수 JSON만 출력 (코드블록 금지):
{{"ops":[...], "reply":"수행한 내용을 한국어 한 문장으로"}}"""


def _brief(scene: Scene) -> str:
    return json.dumps({
        "room": scene.meta.room.model_dump(),
        "equipment": [{"id": e.id, "type": e.type, "box": e.box.model_dump()}
                      for e in scene.equipment],
        "structures": [{"id": s.id, "type": s.type, "box": s.box.model_dump()}
                       for s in scene.structures],
        "pipes": [{"id": p.id, "diameter_mm": p.diameter_mm, "path": p.path}
                  for p in scene.pipes],
    }, ensure_ascii=False)


def _next_id(scene: Scene, prefix: str) -> str:
    ids = {e.id for e in scene.equipment} | {s.id for s in scene.structures} | \
          {p.id for p in scene.pipes}
    n = 1
    while f"{prefix}_{n}" in ids:
        n += 1
    return f"{prefix}_{n}"


def _next_pipe_id(scene: Scene) -> str:
    ids = {p.id for p in scene.pipes}
    n = 101
    while f"P-{n}" in ids:
        n += 1
    return f"P-{n}"


def _find(scene: Scene, oid: str):
    for coll, kind in ((scene.equipment, "equipment"),
                       (scene.structures, "structure"),
                       (scene.pipes, "pipe")):
        for o in coll:
            if o.id == oid:
                return o, kind, coll
    raise ValueError(f"객체 '{oid}' 없음")


def _apply_op(s: Scene, op: dict) -> str:
    k = op["op"]
    if k == "add_equipment":
        t = op["type"]
        size = op.get("size") or TYPE_SIZES[t]
        cx, cy = float(op["center"][0]), float(op["center"][1])
        eid = op.get("id") or _next_id(s, t)
        s.equipment.append(Equipment(id=eid, name=eid, type=t, box=Box(
            min=[cx - size[0] / 2, cy - size[1] / 2, 0],
            max=[cx + size[0] / 2, cy + size[1] / 2, size[2]])))
        return f"{eid} 추가"
    if k == "add_frame":
        x = float(op["x"])
        fid = op.get("id") or _next_id(s, "frame")
        h = s.meta.room.max[2]
        s.structures.append(Structure(id=fid, name=fid, type="frame", box=Box(
            min=[x - 0.1, 0, 0], max=[x + 0.1, 0.4, h])))
        return f"{fid} 추가"
    if k == "move":
        o, kind, _ = _find(s, op["id"])
        d = [float(v) for v in op["delta"]]
        if kind == "pipe":
            o.path = [[p[i] + d[i] for i in range(3)] for p in o.path]
        else:
            o.box.min = [o.box.min[i] + d[i] for i in range(3)]
            o.box.max = [o.box.max[i] + d[i] for i in range(3)]
        return f"{op['id']} 이동"
    if k == "delete":
        o, _, coll = _find(s, op["id"])
        coll.remove(o)
        return f"{op['id']} 삭제"
    if k == "add_pipe":
        pid = op.get("id") or _next_pipe_id(s)
        path = [[float(c) for c in pt] for pt in op["path"]]
        if len(path) < 2:
            raise ValueError("경유점 2개 이상 필요")
        s.pipes.append(Pipe(id=pid, name=pid, system="custom",
                            diameter_mm=float(op.get("diameter_mm", 80)), path=path))
        return f"{pid} 추가"
    if k == "set_diameter":
        o, kind, _ = _find(s, op["id"])
        if kind != "pipe":
            raise ValueError(f"{op['id']}는 배관이 아님")
        o.diameter_mm = float(op["diameter_mm"])
        return f"{op['id']} 직경 변경"
    raise ValueError(f"알 수 없는 op '{k}'")


def run_command(scene: Scene, text: str) -> dict[str, Any]:
    out = _call_claude(PROMPT.format(scene=_brief(scene), text=text))
    if out is None:
        return {"error": "AI 호출에 실패했습니다 (Claude CLI 상태를 확인하세요)."}
    s = copy.deepcopy(scene)
    done, errors = [], []
    for op in out.get("ops") or []:
        try:
            done.append(_apply_op(s, op))
        except Exception as e:  # keep applying the rest
            errors.append(f"{op.get('op', '?')}: {e}")
    return {
        "scene": s if done else None,
        "reply": out.get("reply", ""),
        "applied": done,
        "errors": errors,
    }
