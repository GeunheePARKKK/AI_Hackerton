"""Help-desk chatbot: answers questions about equipment, layout rules and
how to use this tool. Read-only — it never modifies the design."""
from __future__ import annotations

import json

from backend.commands import _brief
from backend.detector import inspect_scene
from backend.llm import _load_knowledge, llm_text
from backend.models import Scene

PROMPT = """당신은 'AI Ship Design Debugger'에 내장된 조선 설계 도우미 챗봇입니다.
비전공자도 이해할 수 있게 쉬운 말로, 간결하게(2~5문장, 필요하면 짧은 목록) 한국어로 답하세요.
설계를 직접 수정할 수는 없습니다. 수정 요청을 받으면 상단 'AI Copilot' 입력창이나 편집 도구 사용법을 안내하세요.

[이 도구 사용법]
- 왼쪽 패널: 장비 추가(종류 선택 후 +장비 추가), 배관 추가(직경 입력), 선택 항목 삭제, Properties에서 ID/이름/직경/크기 편집
- 가운데 3D 화면: 클릭=선택(이동 기즈모 표시), 드래그=회전, 휠=줌 / 배관 선택 후 노란 점 드래그=경로 수정, 노란 점 더블클릭=경유점 추가, Shift+클릭=경유점 삭제
- 오른쪽 패널: AI Copilot(자연어로 설계 명령), 설계 검사 실행, 전체 자동 수정(Agent), 오류 카드 클릭=해결안 보기/AI 분석
- 헤더: ↶↷ 실행취소/재실행(Ctrl+Z/Y), 💾 저장, ↩ 되돌리기(마지막 저장 상태로)

[장비 역할]
- pump(펌프): 유체를 밀어 이송 / heat_exchanger(열교환기): 뜨거운 유체와 차가운 유체 사이 열 교환(냉각용)
- generator(발전기): 선내 전기 생산 / engine(주기관): 배를 추진하는 메인 엔진 / tank(탱크): 연료·청수 등 저장
- web frame(웹 프레임): 선체를 보강하는 뼈대 구조물 / 배관(pipe): 장비 사이 유체가 흐르는 관

[설계 규정 지식]
{rules}

[과거 설계 사례]
{cases}

[현재 설계 상태 (단위 m, Z-up)]
{scene}

[현재 검출된 위반]
{violations}

[대화 기록]
{history}

사용자 질문: "{text}"

답변 텍스트만 출력하세요 (JSON·코드블록·마크다운 서식 금지, 일반 텍스트로)."""


def answer(scene: Scene, text: str, history: list[dict]) -> str:
    kb = _load_knowledge()
    ins = inspect_scene(scene)
    violations = [
        f"{v['id']} {v['code']}: {v['detail']}" for v in ins["violations"]
    ] or ["없음 (모든 검사 통과)"]
    hist = "\n".join(
        f"{'사용자' if m.get('role') == 'user' else '도우미'}: {m.get('text', '')[:300]}"
        for m in history[-8:]) or "(첫 대화)"
    prompt = PROMPT.format(
        rules=json.dumps(kb["rules"], ensure_ascii=False),
        cases=json.dumps(kb["cases"], ensure_ascii=False),
        scene=_brief(scene),
        violations="\n".join(violations),
        history=hist,
        text=text[:500],
    )
    reply = llm_text(prompt)
    return reply or "죄송합니다, 지금은 답변 생성에 실패했습니다. Claude CLI 상태를 확인해주세요."
