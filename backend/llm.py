"""LLM explanation layer (Explain + Learn).

Role separation: every number and every fix candidate comes from the
deterministic engines (detector/resolver). The LLM only turns those verified
facts into an engineer-friendly explanation and cites similar past cases.

Backend: Claude Code CLI in headless mode (`claude -p`), authenticated via
the user's Claude Max subscription. Falls back to a template if unavailable.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "data" / "knowledge.json"
CLAUDE_TIMEOUT_S = 90
HTTP_TIMEOUT_S = 60


def _load_env() -> None:
    """Load KEY=VALUE pairs from repo-root .env (gitignored) into os.environ."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _load_knowledge() -> dict:
    return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))


def retrieve_knowledge(violation: dict) -> dict:
    """RAG-lite: select rules/cases whose tags match the violation."""
    kb = _load_knowledge()
    keys = {violation["code"], violation["a"]["kind"], violation["b"]["kind"],
            violation["a"]["id"].split("_")[0], violation["b"]["id"].split("_")[0]}
    keys = {k.lower() for k in keys} | {violation["code"]}

    def match(item):
        return any(t == violation["code"] or t.lower() in keys for t in item["tags"])

    return {
        "rules": [r for r in kb["rules"] if match(r)][:2],
        "cases": [c for c in kb["cases"] if match(c)][:2],
    }


def _build_prompt(violation: dict, candidates: list[dict], knowledge: dict) -> str:
    facts = {
        "violation": violation,
        "verified_fix_candidates": [
            {k: c[k] for k in ("option", "description", "impact",
                               "displacement_mm", "violations_after", "recommended")}
            for c in candidates
        ],
        "design_rules": knowledge["rules"],
        "past_cases": knowledge["cases"],
    }
    return f"""당신은 조선소 선체의장 설계 검토 전문가입니다. 아래 JSON은 결정론적 기하 검증 엔진이 검출한 설계 오류와, 시뮬레이션으로 이미 검증된 해결안 후보입니다.

{json.dumps(facts, ensure_ascii=False, indent=1)}

위 데이터만 근거로 설계자에게 보고서를 작성하세요. 반드시 아래 JSON 형식으로만 답하세요(마크다운 코드블록 없이 순수 JSON만):
{{
 "why": "이 위반이 왜 문제인지 2-3문장 (관련 규정 근거 인용)",
 "impact": ["예상되는 실무 영향 3개 (생산/일정/비용 관점)"],
 "recommendation": "추천안과 그 이유 2-3문장 (다른 안과의 비교 포함)",
 "past_case": "가장 유사한 과거 사례 요약과 당시 해결 방법 1-2문장"
}}

규칙: 제공된 수치를 절대 바꾸거나 새로 만들지 마세요. 제공된 데이터에 없는 사실을 지어내지 마세요."""


def _claude_text(prompt: str) -> str | None:
    """Run claude CLI headless and return the raw text reply."""
    exe = shutil.which("claude")
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "-p", prompt, "--output-format", "json",
             "--model", "haiku",
             "--disallowed-tools", "*"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=CLAUDE_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return None
        envelope = json.loads(proc.stdout)
        return (envelope.get("result") or "").strip() or None
    except Exception:
        return None


def _post_json(url: str, payload: dict, headers: dict) -> dict | None:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.load(resp)
    except Exception:
        return None


def _gemini_text(prompt: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    out = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"contents": [{"parts": [{"text": prompt}]}],
         # this workload needs no deliberation; thinking multiplies latency
         "generationConfig": {"thinkingConfig": {"thinkingLevel": "minimal"}}},
        {"x-goog-api-key": key})
    try:
        parts = out["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text.strip() or None
    except Exception:
        return None


def _openai_compat_text(prompt: str, url: str, key: str, model: str) -> str | None:
    out = _post_json(url, {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }, {"Authorization": f"Bearer {key}"})
    try:
        return out["choices"][0]["message"]["content"].strip() or None
    except Exception:
        return None


def llm_text(prompt: str) -> str | None:
    """Fast-provider dispatch: Gemini/Groq/OpenAI via direct HTTP if an API key
    is configured (1-3s), otherwise fall back to the Claude Code CLI (slower
    because every call cold-starts a full CLI session)."""
    if os.environ.get("GEMINI_API_KEY"):
        r = _gemini_text(prompt)
        if r:
            return r
    if os.environ.get("GROQ_API_KEY"):
        r = _openai_compat_text(
            prompt, "https://api.groq.com/openai/v1/chat/completions",
            os.environ["GROQ_API_KEY"],
            os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"))
        if r:
            return r
    if os.environ.get("OPENAI_API_KEY"):
        r = _openai_compat_text(
            prompt, "https://api.openai.com/v1/chat/completions",
            os.environ["OPENAI_API_KEY"],
            os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        if r:
            return r
    return _claude_text(prompt)


def _call_claude(prompt: str) -> dict | None:
    """Run the configured LLM and parse its reply as JSON."""
    text = llm_text(prompt)
    if text is None:
        return None
    try:
        # strip accidental code fences
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):text.rfind("}") + 1]
        return json.loads(text)
    except Exception:
        return None


def _fallback(violation: dict, candidates: list[dict], knowledge: dict) -> dict:
    rule = knowledge["rules"][0] if knowledge["rules"] else None
    case = knowledge["cases"][0] if knowledge["cases"] else None
    rec = next((c for c in candidates if c.get("recommended")), None)
    return {
        "why": (f"{violation['detail']} — " + (rule["content"] if rule else "설계 기준 위반입니다.")),
        "impact": ["탑재/설치 단계 간섭으로 재작업 가능성", "생산 일정 지연 위험", "수정 비용 증가 (설계 단계 대비 후공정 수정 비용 상승)"],
        "recommendation": (f"{rec['option']}안({rec['description']})을 권장합니다. 영향: {rec['impact']}."
                           if rec else "자동 해결안이 없어 수동 검토가 필요합니다."),
        "past_case": (f"[{case['project']}] {case['problem']} → {case['resolution']}. {case['lesson']}"
                      if case else "유사 사례가 등록되어 있지 않습니다."),
        "llm": False,
    }


def explain_violation(violation: dict, candidates: list[dict]) -> dict[str, Any]:
    key = json.dumps([violation, candidates], sort_keys=True, ensure_ascii=False)
    if key in _CACHE:
        return _CACHE[key]
    knowledge = retrieve_knowledge(violation)
    result = _call_claude(_build_prompt(violation, candidates, knowledge))
    if result is None:
        result = _fallback(violation, candidates, knowledge)
    else:
        result["llm"] = True
    result["knowledge_used"] = {
        "rules": [r["id"] for r in knowledge["rules"]],
        "cases": [c["id"] for c in knowledge["cases"]],
    }
    _CACHE[key] = result
    return result


_CACHE: dict[str, dict] = {}
