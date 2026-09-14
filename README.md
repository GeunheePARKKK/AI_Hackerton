# 🛳️ AI Ship Design Debugger

> **AI 기반 선박 설계 검증 & 해결 지원 에이전트**
> 기존 CAD가 설계의 문제를 "찾아낸다"면, 우리는 그 문제를 **이해하고 어떻게 해결할지까지 제안**한다.

개발자가 디버거로 코드 오류를 잡듯이, 조선 설계자가 작성한 3D 설계안을 AI가 검토하고 **오류의 원인 · 영향 · 해결 방법 · 과거 유사 사례**까지 제시하는 시스템입니다.

```
Human Design → AI Critic → Human Revision
```

AI는 설계자를 대체하지 않습니다. 검토·분석·수정 의사결정을 지원합니다.

## 데모 흐름

1. **Detect** — 가상 기관실 설계에서 Rule Engine이 106건 검사 → 위반 4건 검출 (배관↔구조물 관통, 이격거리 위반, 배관 간 간섭, 유지보수 공간 침범)
2. **Visualize** — 3D 뷰에서 위반 객체 하이라이트 + 위반 지점 마커 + 클릭 시 카메라 포커스
3. **Recommend** — 해결안 후보를 기하적으로 생성하고, **수정된 설계에 Rule Engine을 재실행해 검증된 후보만** A/B안으로 제시 (초록 고스트로 수정 후 미리보기)
4. **Explain + Learn** — Claude가 설계 규정과 과거 사례 KB를 근거로 "왜 문제인지 / 예상 영향 / 추천 근거 / 과거 유사 사례"를 자연어 리포트로 생성
5. **Apply** — 설계자가 최종 판단 후 적용 → 재검사 → 위반 감소 확인

## 아키텍처 — 역할 분리 원칙

**모든 수치와 판정은 결정론적 엔진에서, LLM은 설명만.** AI가 근거 없는 엔지니어링 수치를 만들어내지 않습니다.

```
engine_room.json (설계 데이터)
        ↓
Geometry Engine ──── 선분↔박스, 선분↔선분 최단거리, AABB (정확한 수학)
        ↓
Rule Engine ──────── 간섭/이격거리/유지보수 공간/경계 검사 → 위반 + 실측 수치
        ↓
Resolver ─────────── 후보 생성 → 전체 재검증 → 통과한 후보만 제시 (스코어링/★추천)
        ↓
LLM (Claude) ─────── 검증된 사실 + 규정/사례 KB → 자연어 설명 (수치 생성 금지)
        ↓
설계자 최종 판단 → 적용/초기화
```

## 기술 스택

| 구성 | 기술 |
|---|---|
| Backend | Python 3.14, FastAPI |
| 기하 검증 | 자체 구현 (ternary search segment-box distance, Ericson segment-segment) |
| Frontend | Three.js (빌드 없는 단일 HTML) |
| LLM | Claude (Claude Code CLI headless, `claude -p`) — 실패 시 템플릿 폴백 |
| 지식 검색 | RAG-lite (태그 매칭 기반 규정/사례 KB) |

## 실행 방법

```bash
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000
# → http://localhost:8000
```

AI 분석 기능은 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)가 설치·로그인되어 있으면 자동으로 활성화됩니다. 없으면 템플릿 설명으로 폴백되어 나머지 기능은 전부 동작합니다.

**⚡ AI 응답 속도 높이기 (권장):** Claude CLI 경유는 호출마다 15~25초가 걸립니다. `.env.example`을 `.env`로 복사하고 무료 API 키(예: [Gemini](https://aistudio.google.com/apikey) 또는 [Groq](https://console.groq.com/keys))를 넣으면 직접 HTTP 호출로 1~3초에 응답합니다. 키가 없으면 자동으로 Claude CLI 폴백.

### API

| Endpoint | 설명 |
|---|---|
| `GET /api/scene` | 현재 설계 씬 (장비/구조물/배관) |
| `GET /api/inspect` | Rule Engine 검사 실행 → 위반 목록 |
| `GET /api/resolve/{id}` | 해당 위반의 검증된 해결안 후보 |
| `GET /api/explain/{id}` | LLM 분석 리포트 (원인/영향/추천/사례) |
| `POST /api/apply` | 해결안 적용 (메모리 작업본) |
| `POST /api/reset` | 원본 설계로 복원 |

## 프로젝트 구조

```
backend/
├── main.py          # FastAPI 엔드포인트
├── models.py        # 데이터 모델 (Scene/Equipment/Pipe/Structure)
├── geometry.py      # 기하 계산 (결정론적, LLM 개입 0%)
├── detector.py      # Rule Engine — 간섭/이격/유지보수/경계 검사
├── resolver.py      # 해결안 생성 + 재검증
├── llm.py           # Claude 설명 레이어 + RAG-lite
└── data/
    ├── engine_room.json  # 가상 기관실 (의도적 오류 4건 내장)
    └── knowledge.json    # 설계 규정 + 과거 사례 KB
frontend/
└── index.html       # Three.js 3D 뷰어 + 검증/해결안/AI 분석 UI
```

## 왜 이 구조인가

- 기존 CAD의 Clash Detection은 "어디서 충돌하는가"까지 제공 → 우리는 **검출 이후**(왜/어떻게/과거엔)를 차별점으로
- 해결안은 LLM이 아니라 **시뮬레이션 재검증**으로 보장 → "검증 안 된 추천"이 구조적으로 존재할 수 없음
- 숙련 설계자의 노하우(과거 사례)를 KB화 → `숙련자 → AI → 모든 설계자`로 인수인계를 확장
