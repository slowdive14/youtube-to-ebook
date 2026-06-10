# PLAN: 매일 스피킹 아웃풋 — "오늘의 한 마디" (Gemini 음성 코칭)

> **CRITICAL INSTRUCTIONS**: 각 Phase 완료 후:
> 1. ✅ 완료한 작업 체크박스 체크
> 2. 🧪 Quality Gate 검증 항목 모두 실행
> 3. ⚠️ Quality Gate 전부 통과 확인
> 4. 📅 "Last Updated" 날짜 갱신
> 5. 📝 Notes 섹션에 배운 점 기록
> 6. ➡️ 그 다음에만 다음 Phase로 진행
>
> ⛔ Quality Gate를 건너뛰거나 실패한 상태로 진행하지 말 것

- **Last Updated**: 2026-06-10
- **Status**: ✅ Phase 0~1 완료 → 🔜 Phase 2 진입(핵심: 녹음 UI)
- **Scope**: Medium (5 phases, 약 9~14시간)
- **Stack**: Python(write_articles) / Astro 서버리스(API route) / 브라우저 MediaRecorder / Gemini 2.5 Flash(audio)

---

## 1. Overview & Objectives

기존 Speaking Drill은 **암송 위주 + 브라우저 Web Speech 인식 실패**로 사실상 안 쓰임. 이를 **"하루 한 문장, 내 생각을 직접 말하고 즉시 코칭받는"** 루프로 교체한다.

### 핵심 문제 (검증된 진단)
- **음성인식이 가장 큰 걸림돌**: 브라우저 `webkitSpeechRecognition`은 ① 한국식 억양 영어에 약함 ② 데스크톱 Chrome 외 불안정(모바일·Firefox) ③ 정답 일치 채점이라 한 글자만 틀려도 ❌.
- 4단계(Repeat/Fill/Translate/Swap) 전부 *정해진 문장 따라말하기* → 자기 산출(production)이 0.

### 해결 방향 (실측 검증 완료)
브라우저는 **녹음만**(MediaRecorder) → 오디오를 서버리스로 보내 **Gemini가 전사 + 코칭을 한 호출로** 처리.
- ✅ 억양·잡음에 강함 (Gemini 오디오 이해 ≫ 브라우저 ASR)
- ✅ **기존 GEMINI_API_KEY만** 사용 (새 벤더·Azure 불필요; Azure 키는 현재 401)
- ✅ MediaRecorder는 iOS Safari 포함 거의 전 브라우저 지원
- ✅ "정답 일치 채점" 폐기 → 인식이 조금 틀려도 좌절이 아니라 학습

### 목표
- [ ] 매일 다이제스트에서 **산출형 스피킹 프롬프트 1개** 생성(한국어 질문 + 문장 프레임 + 기사에서 뽑은 재사용 표현 2~3개 + 모델답안)
- [ ] 아카이브에 **`/speak/...` 페이지**: 프롬프트 보여주고 → 🎤 녹음 → Gemini 피드백(전사·칭찬·교정·업그레이드 표현·모델답안 섀도잉)
- [ ] **습관 장치**: 이메일/이슈 페이지의 한 개 CTA, 스트릭, 내 문장 로그
- [ ] 기존 15문장 드릴은 "복습 모드"로 강등(삭제 X)

### 비목표
- 실시간 대화/멀티턴(추후), 발음 음소 점수(추후), 네이티브 앱

---

## 2. Architecture Decisions

| 결정 | 내용 | 이유 |
|------|------|------|
| 브라우저 = 녹음만 | `MediaRecorder` → webm/opus(or mp4) Blob | SpeechRecognition 폐기. 전 브라우저·모바일 지원 |
| 전사+코칭 = Gemini 1호출 | 오디오 `inlineData` + 프롬프트 → JSON | 억양 강건 + 피드백이 공짜로 따라옴 (실측 확인) |
| 서버리스 = Astro API route | `src/pages/api/speak-feedback.ts` | `api/define.ts`가 검증한 패턴(Gemini REST, `process.env.GEMINI_API_KEY`) 재사용 |
| 채점 폐기 | pass/fail 없음, 항상 "교정·모델 제시" | 인식 오류가 학습 차단이 아니라 학습 재료가 됨 |
| 프롬프트 = 산출형 | 정답 암송이 아니라 *내 의견 1문장* + 발판 | B1도 말하게 하면서 진짜 스피킹 |
| 데이터 = frontmatter | `speakingPrompt` 객체를 이슈 md에 | 기존 drillSentences와 동일 경로 |
| 키 노출 0 | Gemini 키는 서버리스에만, 클라이언트 X | define.ts와 동일 보안 모델 |
| TDD 현실 적용 | Python 순수로직만 단위테스트; 서버리스·녹음 UI·AI는 빌드/수동 게이트 | 라이브 오디오·브라우저는 단위테스트 비현실적 (기존 plan 원칙과 동일) |

### 데이터 형태 (frontmatter `speakingPrompt`)
```yaml
speakingPrompt:
  topic: "China's Dirty Money Problem"
  question_ko: "이 돈세탁이 왜 막기 어렵다고 생각해? 영어 한 문장으로 말해봐."
  frame: "I think ___ because ___."
  expressions:
    - { en: "hard to trace", ko: "추적하기 어렵다" }
    - { en: "exploit a loophole", ko: "허점을 악용하다" }
  model: "I think it's hard to stop because the money is hard to trace."
```

### API 계약 (`POST /api/speak-feedback`)
- 요청(JSON): `{ audioBase64, mimeType, question, model }`
- 응답(JSON): `{ transcript, good, corrected, upgrade, model_answer }`
- 검증: mimeType allowlist(webm/mp4/ogg/mpeg/wav), base64 크기 상한(~2MB), 키 미설정 500

---

## 3. Phases

### Phase 0 — 스피킹 프롬프트 생성 + 스키마 (2-3h)
**Goal**: 매일 다이제스트에서 산출형 프롬프트 1개를 만들어 이슈 frontmatter에 싣는다.

**Test Strategy**: 프롬프트 빌더·JSON 파싱/검증을 순수함수 단위테스트(Gemini mock). `generate_drill_sentences` 패턴 재사용.

**Tasks**:
- [x] **(RED)** `test_speaking_prompt.py`:
  - `build_speaking_prompt_request(article)` → "산출형/프레임/표현/모델답안/JSON only" 지시 포함
  - `parse_speaking_prompt(text)` → `{topic,question_ko,frame,expressions[],model}`, 코드펜스/잘림 salvage, 필수(question_ko/frame/model) 누락 시 None
  - 검증: expressions ≤3 클램프, 깨진 항목 필터, topic 기본 ""
  - → 실패 확인(ImportError)
- [x] **(GREEN)** `write_articles.generate_speaking_prompt(en_articles)` — 1번 기사 기준, thinking_budget=0, JSON 강제
- [x] **(GREEN)** `export_archive._build_speaking_yaml` + `generate_issue_markdown(speaking_prompt=)` + `export_newsletter_issue(speaking_prompt=)`
- [x] **(GREEN)** `content.config.ts`: `speakingPrompt` zod 스키마(optional) 추가
- [x] **(GREEN)** `main.py`: STEP 3a1에서 `generate_speaking_prompt` 호출(non-fatal) + export로 전달
- [x] **(REFACTOR)** 영문 기사 기준 1회 생성(EN만)

**Quality Gate**:
- [x] `pytest test_speaking_prompt.py`(12) + 전체 회귀 145 통과
- [x] 실제 1편 라이브 산출 확인: 한국어 질문 + 프레임 + 표현 3개(한글뜻) + 모델답안 정상
- [x] frontmatter 직렬화 단위테스트(4) + **`astro build` 통과**(스키마 유효, 기존 이슈 하위호환)
- [x] Gemini 키 로그 미노출 (서버리스 아님, 파이프라인 내부)

**Dependencies**: 없음
**Rollback**: `generate_speaking_prompt`/frontmatter/스키마 추가분 revert (drill은 그대로)

---

### Phase 1 — 서버리스 피드백 엔드포인트 (2-3h)
**Goal**: 오디오를 받아 Gemini로 전사+코칭하는 `/api/speak-feedback` 추가.

**Test Strategy**: 서버리스(TS)라 pytest 대상 아님 → 빌드 통과 + 로컬 호출(curl/스크립트) 수동 게이트. 입력 검증 로직은 작게 유지.

**Tasks**:
- [x] **(GREEN)** `src/pages/api/speak-feedback.ts` (`prerender=false`) — `define.ts` 구조 복제:
  - body: `{ audioBase64, mimeType, question, model }`
  - Gemini REST `inlineData` 오디오 파트 + `responseMimeType:application/json` + `thinkingConfig.thinkingBudget=0`
  - 응답 파싱(thought 파트 제외, fence strip) → JSON `{transcript,good,corrected,upgrade,model_answer}`
- [x] mimeType allowlist(codecs param strip) + base64 3MB 상한 + 키 미설정 500 + 과대 413 + 미지원 415 + Gemini 502
- [x] **(검증)** Gemini REST 오디오+JSON 계약을 동일 호출로 실측: webm/opus 정확 전사 + 코칭 JSON, `responseMimeType=json`이 깔끔한 JSON 반환(파싱 OK)
- [x] **(REFACTOR)** 코칭 프롬프트 상수화, 한국어 톤(격려·"정답아님"·억양 비처벌) 고정

**Quality Gate**:
- [x] `astro build` 통과(라우트 타입체크)
- [x] 핵심 호출(오디오→Gemini→JSON) 실측 통과. **HTTP 라우트 풀 왕복은 Phase 2 UI에서 실사용으로 검증**
- [x] 잘못된 mimeType/과대 payload/키 없음 분기 구현(415/413/500)
- [x] 응답에 Gemini 키·원시 오류 미노출(키는 서버리스 env, 오류는 일반 메시지)

**Dependencies**: 없음(Phase 0과 병행 가능). Vercel에 `GEMINI_API_KEY` 환경변수(이미 define.ts가 사용 중).
**Rollback**: 라우트 파일 삭제

---

### Phase 2 — 녹음 UI `/speak/[issue]` (3-4h) [핵심]
**Goal**: 프롬프트 표시 → 🎤 녹음 → 피드백 렌더. SpeechRecognition 완전 대체.

**Test Strategy**: 브라우저/마이크/AI라 단위테스트 비현실 → 빌드 + 데스크톱·모바일 수동 E2E.

**Tasks**:
- [ ] **(GREEN)** `src/pages/speak/[...slug].astro` (`getStaticPaths`로 `speakingPrompt` 있는 이슈만):
  - 상단: topic + 한국어 질문 + 프레임 + 표현 칩 2~3개(탭하면 TTS 발음)
  - 🎤 **녹음 버튼**: `MediaRecorder`로 캡처 → Blob → base64 → `/api/speak-feedback` POST
  - 상태머신: idle → (권한요청) → recording → processing → result / error→retry
  - 결과: 내가 말한 전사 / ✅칭찬 / ✏️교정 / 🌟업그레이드 표현 / 🔊모델답안(TTS 재생 = 마무리 섀도잉)
- [ ] 브라우저별 mimeType 처리(`MediaRecorder.isTypeSupported`로 webm/opus or mp4 선택 후 그대로 전송)
- [ ] 마이크 거부/미지원/네트워크 오류 친화적 메시지
- [ ] **(REFACTOR)** 재녹음·다시듣기·"한 번 더" 버튼, 로딩 스피너

**Quality Gate**:
- [ ] `npm run build` 통과
- [ ] **데스크톱 Chrome**: 녹음→피드백 1분 내 왕복 정상
- [ ] **모바일(iOS Safari/Android Chrome)**: 녹음→피드백 정상(가장 중요한 실사용 환경)
- [ ] **🔑 내 실제 억양 영어**로 전사 정확도 체감 확인(기존 Web Speech 대비 개선)
- [ ] 마이크 거부 시 앱이 깨지지 않고 안내

**Dependencies**: Phase 0(프롬프트), Phase 1(엔드포인트)
**Rollback**: `/speak` 페이지 삭제(드릴/이슈 영향 없음)

---

### Phase 3 — 습관 루프: 진입점 + 스트릭 + 로그 (2-3h)
**Goal**: 매일 1번 끌어들이고, 끊기지 않게, 성장을 눈에 보이게.

**Test Strategy**: localStorage 순수 로직(스트릭 계산) 단위테스트(JS) 또는 수동. 진입점은 수동.

**Tasks**:
- [ ] 이슈 페이지·아침 이메일에 **단일 CTA** `🎤 오늘의 한 마디` → `/speak/<오늘 이슈>` 딥링크
- [ ] **스트릭**(localStorage): 마지막 수행일 기준 연속일 계산·표시("🔥 N일")
- [ ] **내 문장 로그**(localStorage): 그날 전사 + 교정본 저장, /speak에서 최근 기록 보기
- [ ] (선택) 로그를 마크다운으로 내보내 `english-study-review` 워크플로와 연결
- [ ] **(REFACTOR)** 스트릭 경계(자정/하루 빠짐) 처리

**Quality Gate**:
- [ ] 이메일/이슈의 CTA가 오늘 `/speak`로 이동
- [ ] 하루 1회 수행 시 스트릭 +1, 하루 빠지면 리셋(경계 검증)
- [ ] 로그가 새로고침 후에도 유지

**Dependencies**: Phase 2
**Rollback**: CTA/스트릭/로그 제거(핵심 기능엔 영향 없음)

---

### Phase 4 — 기존 드릴 강등 + 마감 (1-2h)
**Goal**: 스피킹을 메인으로, 옛 15문장 드릴은 보조로.

**Tasks**:
- [ ] 이슈/네비에서 메인 = `/speak`, 드릴은 "더 연습하기(15문장)" 보조 링크로
- [ ] 카피·접근성·에러 문구 정리, 모바일 레이아웃 점검
- [ ] README/CLAUDE.md에 새 기능·`/api/speak-feedback`·env 기재

**Quality Gate**:
- [ ] `npm run build` 통과 + 전체 pytest 통과
- [ ] 메인 동선이 스피킹으로 바뀌고 드릴도 여전히 접근 가능
- [ ] 문서 갱신 완료

**Dependencies**: Phase 2,3
**Rollback**: 네비/문서 되돌리기

---

## 4. Risk Assessment

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| 내 억양에서 전사 정확도 부족 | Low | High | Gemini 오디오는 억양에 강함(원어민 클립 실측 통과). Phase 2에서 실제 목소리로 확인, 코칭은 채점 아님이라 오류 내성 |
| MediaRecorder 포맷 브라우저별 상이 | Med | Med | `isTypeSupported`로 webm/mp4 택1 후 그대로 mimeType 전송(Gemini가 다 수용 — webm 실측 통과) |
| Vercel 서버리스 페이로드/시간 제한 | Low | Med | 문장 클립 수십~수백 KB로 작음, base64도 <1MB. 응답 ~3-5s |
| iOS Safari 마이크/자동재생 제약 | Med | Med | 사용자 제스처로 녹음·TTS 트리거, 권한 안내 UI |
| Gemini 키/비용 | Low | Low | flash audio 저렴, 키는 서버리스에만 |
| 스트릭 경계 버그 | Low | Low | 날짜 경계 단위테스트 |

> ⚠️ 본 기능은 개인 학습용. 녹음 오디오는 피드백 후 보관하지 않음(서버리스는 즉시 폐기), 로그는 텍스트만 localStorage.

---

## 5. Progress Tracking

| Phase | 상태 | 완료일 |
|-------|------|--------|
| 0. 프롬프트 생성 + 스키마 | ✅ 완료 | 2026-06-10 |
| 1. 서버리스 피드백 엔드포인트 | ✅ 완료 | 2026-06-10 |
| 2. 녹음 UI `/speak` | ⬜ 대기 | - |
| 3. 습관 루프(진입·스트릭·로그) | ⬜ 대기 | - |
| 4. 드릴 강등 + 마감 | ⬜ 대기 | - |

상태 범례: ⬜ 대기 / 🔄 진행중 / ✅ 완료 / ⚠️ 막힘

---

## 6. Notes & Learnings

> 각 Phase 진행하며 배운 점·막힌 점 기록.

- (사전검증 ✅) Gemini 오디오 전사 실측: 팟캐스트 mp3 클립 정확 전사, **webm/opus(Chrome 녹음 포맷)도 정확**. `types.Part.from_bytes(data, mime_type)` / REST `inlineData`. 전사+코칭(JSON: transcript·good·corrected·upgrade·model)이 **한 호출**로 동작 확인 → 브라우저 SpeechRecognition 불필요.
- (사전검증) `api/define.ts`가 서버리스에서 Gemini REST를 `process.env.GEMINI_API_KEY`로 호출하는 검증된 패턴 — `/api/speak-feedback`는 여기에 `inlineData` 오디오 파트만 추가.
- (설계 원칙) "정답 일치 채점" 폐기가 핵심: 인식이 완벽할 필요가 없어짐 → 가장 큰 걸림돌(억양 인식 실패)이 구조적으로 제거됨.
- (Phase 0 실측 ✅) `generate_speaking_prompt` 라이브: topic/question_ko/frame/expressions(3, 한글뜻)/model 정상. `astro build`로 `speakingPrompt` 스키마가 기존 전 이슈와 하위호환 검증.
- (Phase 1 실측 ✅) `/api/speak-feedback`은 `define.ts` 패턴 + 오디오 `inlineData`. **`responseMimeType:application/json`이 결정적** — Gemini가 fence 없는 순수 JSON 반환(파싱 안정). 동일 REST 호출 실측: webm/opus 정확 전사 + transcript·good·corrected·upgrade·model_answer 전부 채워짐. 라우트는 컴파일 통과, HTTP 풀 왕복은 Phase 2 UI에서 실증.
- (배포 토폴로지) `youtube-digest-archive`는 **메인 repo의 일부**(동일 origin). Vercel이 이 repo에서 배포하고, 파이프라인의 `push_to_archive_repo`도 같은 repo에 커밋 → 단일 소스. `GEMINI_API_KEY`는 이미 Vercel env에 있음(define.ts가 사용 중).
