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
- **Status**: ✅ 전 Phase(0~4) 완료 — 기능 라이브(매일 다이제스트부터 `speakingPrompt` 자동 생성)
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
- [x] **(GREEN)** `src/pages/speak/[...slug].astro` (`getStaticPaths`로 `speakingPrompt` 있는 이슈만):
  - 상단: topic + 한국어 질문 + 프레임 + 표현 칩(탭하면 TTS 발음)
  - 🎤 **녹음 버튼**: `MediaRecorder`로 캡처 → Blob → base64 → `/api/speak-feedback` POST
  - 상태머신: idle → recording(20s 안전 자동정지) → processing → result / error→retry
  - 결과: 전사 / ✅칭찬 / ✏️교정 / 🌟업그레이드 / 🔊모델답안(TTS 재생) + "한 번 더"
- [x] 브라우저별 mimeType 처리(`isTypeSupported`로 webm/opus·webm·mp4·ogg 택1, blob.type 그대로 전송)
- [x] 마이크 거부/미지원/네트워크 오류 친화적 한국어 메시지
- [x] **(REFACTOR)** 펄스 애니메이션, "한 번 더" 리셋, localStorage 로그 기록(Phase 3 토대)
- [x] 테스트용으로 `2026-06-08_02.md`(China's Dirty Money)에 `speakingPrompt` 추가 → 배포본에서 즉시 체험 가능

**Quality Gate**:
- [x] `astro build` 통과 + 해당 이슈로 `/speak/2026-06-08_02` 페이지 정상 생성(요소 렌더 확인)
- [ ] ▶ **사용자 검증(배포 후)**: 데스크톱 Chrome 녹음→피드백 왕복
- [ ] ▶ **사용자 검증(배포 후)**: **모바일(iOS Safari/Android Chrome)** 녹음→피드백 — 핵심 실사용 환경
- [ ] ▶ **사용자 검증(배포 후)**: **🔑 내 실제 억양 영어** 전사 정확도(기존 Web Speech 대비 개선 체감)
- [x] 마이크 거부/미지원 시 앱이 깨지지 않고 안내(코드 처리)

**Dependencies**: Phase 0(프롬프트), Phase 1(엔드포인트)
**Rollback**: `/speak` 페이지 삭제(드릴/이슈 영향 없음)

---

### Phase 3 — 습관 루프: 진입점 + 스트릭 + 로그 (2-3h)
**Goal**: 매일 1번 끌어들이고, 끊기지 않게, 성장을 눈에 보이게.

**Test Strategy**: localStorage 순수 로직(스트릭 계산) 단위테스트(JS) 또는 수동. 진입점은 수동.

**Tasks**:
- [x] 이슈 페이지에 **단일 CTA** `🎤 오늘의 한 마디` → `/speak/<이슈>` (drill 링크 위, 더 눈에 띄는 빨간 pill)
- [x] **스트릭**(localStorage): 로컬 캘린더 day 기준 연속일 계산·표시("🔥 N일"), 오늘 미수행 시 어제까지 유효(grace)
- [x] **내 문장 로그**(localStorage): 그날 전사+교정 저장, /speak에서 날짜별 최근 7개 표시(load 시점부터 과거 기록도)
- [~] (선택) 로그 마크다운 내보내기 → 보류(추후 `english-study-review` 연동)
- [x] **(REFACTOR)** 스트릭 경계: **타임존 버그 수정**(UTC `toISOString` → 로컬 day), 중복 당일 1회 카운트
- [~] 아침 이메일 CTA → **보류**: 이메일 파이프라인 비활성 + 아카이브 base URL 컨텍스트 없음

**Quality Gate**:
- [x] 이슈의 CTA가 `/speak/<이슈>`로 이동(빌드 링크 생성 확인)
- [x] 스트릭 계산 **node로 7개 케이스 전부 PASS**(연속/grace/끊김/중복당일/공백)
- [x] 로그는 표준 localStorage 영속(새로고침 유지) — load 시 `renderStreakAndLog()`로 과거 기록 복원
- [x] `astro build` 통과(이슈 CTA + 스트릭/로그 페이지 생성)

**Dependencies**: Phase 2
**Rollback**: CTA/스트릭/로그 제거(핵심 기능엔 영향 없음)

---

### Phase 4 — 기존 드릴 강등 + 마감 (1-2h)
**Goal**: 스피킹을 메인으로, 옛 15문장 드릴은 보조로.

**Tasks**:
- [x] 이슈 메인 동선 = `/speak`(빨간 pill CTA 상위), 드릴은 "더 연습하기" 보조 링크(이슈+speak 양쪽)
- [x] 모바일 우선 레이아웃, 친화적 한국어 에러 문구(Phase 2에서 처리)
- [x] `CLAUDE.md`에 Daily Speaking Output 섹션(프롬프트·`/api/speak-feedback`·습관루프·배포 주의)

**Quality Gate**:
- [x] `astro build` 통과 + 전체 pytest 145 통과
- [x] 메인 동선이 스피킹으로 바뀌고 드릴도 여전히 접근 가능
- [x] 문서 갱신 완료

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
| 2. 녹음 UI `/speak` | ✅ 완료(기기·억양 검증 통과) | 2026-06-10 |
| 3. 습관 루프(진입·스트릭·로그) | ✅ 완료 | 2026-06-10 |
| 4. 드릴 강등 + 마감 | ✅ 완료 | 2026-06-10 |

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
- (배포 주의 ⚠️) **git push만으로는 사이트 반영 안 됨** — Vercel이 Deploy Hook 트리거 방식. 사이트 변경 후 반드시 `trigger_vercel_deploy()`(또는 hook POST) 실행해야 화면 반영. (Phase 2 배포 시 이걸 빠뜨려 "안 보임" 발생 → hook 쏘고 해결.)
- (Phase 2 실측 ✅) 사용자 실제 기기·억양에서 녹음→전사→코칭 **정상 동작 확인("잘 잡힌다")**. 브라우저 SpeechRecognition 대비 핵심 개선 입증.
- (Phase 3 실측 ✅) 스트릭 = **로컬 캘린더 day** 기준. `toISOString()`(UTC)을 쓰면 KST에서 하루 밀리는 버그 → `getFullYear/Month/Date`로 로컬 day 생성. grace(오늘 미수행 시 어제까지 유효). node로 7케이스 검증. 이슈 페이지에 빨간 pill CTA(drill보다 상위). 로그는 날짜별 dedupe 최근 7개.
- (후속 ✅ 드릴↔스피킹 연결) 사용자 피드백: 기존 드릴이 난도 높고(빈칸/번역/단어교체) Web Speech 인식률 저조해 안 씀. → `/speak`를 **2단계 흐름**으로 재구성: ①워밍업=드릴 문장(첫 3개) **따라 말하기(shadowing)** ②본 과제=내 문장 산출. 둘 다 MediaRecorder→Gemini(Web Speech 폐기, 합/불 없음). `/api/speak-feedback`에 **`mode:'shadow'`** 추가(목표 문장 비교, 관대한 피드백 `{transcript,good,tip}`). 녹음기를 다중 타겟 재사용하도록 일반화. 옛 4단계 `/drill`은 "더 어려운 연습"으로 강등 링크만 유지. shadow REST 계약 실측: 정확 전사 + 한국어 격려 + 발음 팁 정상.
