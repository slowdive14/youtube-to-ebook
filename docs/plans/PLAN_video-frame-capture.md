# PLAN: 유튜브 영상 화면 캡처 → 기사 인라인 삽입

> **CRITICAL INSTRUCTIONS**: 각 Phase 완료 후:
> 1. ✅ 완료한 작업 체크박스 체크
> 2. 🧪 Quality Gate 검증 항목 모두 실행
> 3. ⚠️ Quality Gate 전부 통과 확인
> 4. 📅 "Last Updated" 날짜 갱신
> 5. 📝 Notes 섹션에 배운 점 기록
> 6. ➡️ 그 다음에만 다음 Phase로 진행
>
> ⛔ Quality Gate를 건너뛰거나 실패한 상태로 진행하지 말 것

- **Last Updated**: 2026-05-27
- **Status**: ✅ Phase 0~4 완료 → 🔜 Phase 5 진입(마지막)
- **Scope**: Medium~Large (6 phases, 약 10~16시간)
- **Stack**: Python 3.14 / yt-dlp / ffmpeg / Gemini API (+Vision) / Cloudflare R2
- **참고 계획**: `C:\Users\user\Downloads\knou\docs\plans\PLAN_knou-lms-auto.md` (Phase 5·6·6.5의 타임스탬프→ffmpeg 프레임→Gemini 비전 선별→마크다운 임베드 패턴을 이식)

---

## 1. Overview & Objectives

각 유튜브 영상의 **핵심 장면을 자동 캡처**해 생성된 기사 본문에 **섹션별 인라인 이미지**로 삽입한다. 텍스트만 있던 다이제스트가 시각 자료를 갖춘 매거진으로 업그레이드된다.

### 목표
- [ ] 트랜스크립트의 **타임스탬프를 보존**(현재는 텍스트만 남기고 버림)
- [ ] Gemini가 기사 핵심 개념마다 **영상 타임스탬프 마커 `[MM:SS]`** 를 붙이도록
- [ ] 영상당 **3~4개 핵심 시점**을 골라 yt-dlp+ffmpeg로 **실제 프레임 추출**
- [ ] **Gemini 비전으로 후보 프레임 중 최적 1장 선별**(검은화면·전환장면 회피, KNOU 6.5 방식)
- [ ] 프레임을 **R2에 업로드**(기존 오디오 업로드 인프라 재사용)하고 아카이브 마크다운의 **해당 섹션 아래 `![caption](url)` 인라인 삽입**
- [ ] 이메일 HTML·EPUB에도 동일 이미지 노출(선택)
- [ ] 캡처 실패해도 기사 자체는 깨지지 않음(graceful degradation)

### 사용자 결정 (확정)
- 배치 = **섹션별 인라인** (개념마다 해당 위치에 이미지)
- 품질 선별 = **Gemini 비전 사용** (강당 ~$0.02)
- 추출 수 = **영상당 3~4장**

### 비목표 (Out of scope)
- 영상 전체 다운로드 아카이빙 (프레임만 추출)
- Shorts 영상 캡처 (이미 파이프라인에서 제외됨)
- 자막 번역/하드섭

---

## 2. Architecture Decisions

| 결정 | 내용 | 이유 |
|------|------|------|
| **yt-dlp 스트림 URL + ffmpeg seek** | 영상 전체 다운로드 대신 직접 스트림 URL에 `-ss` seek | 디스크·시간 절약. 단 4장이면 360p 단일 다운로드가 더 빠를 수 있어 Phase 0에서 실측 결정 |
| **타임스탬프 = 트랜스크립트 snippet.start** | `youtube-transcript-api` snippet의 `start`(초)를 보존 | 별도 영상 분석 불필요, 자막 동기 = 화면 동기 근사 |
| **프레임 시점 선택 = Gemini(텍스트)** | 기사+타임스탬프 세그먼트를 주고 "시각화 가치 높은 3~4 시점" 선정 | 말풍선 위주 talking-head 회피, 슬라이드·시연·b-roll 우선 |
| **프레임 품질 선별 = Gemini 비전** | 시점 ±오프셋 후보 N장 → 비전이 1장 픽 | 자막 시점 ≠ 슬라이드 표시 시점 어긋남 보정(KNOU 6.5 실증) |
| **저장 = Cloudflare R2** | `export_archive`의 boto3 R2 클라이언트 일반화 | 이메일·웹 양쪽에서 `<img src>` 로 접근, 이미 검증된 경로 |
| **임베드 = 마커 기반 치환** | 기사 내 `[[FRAME:MM:SS]]` 플레이스홀더를 `![cap](url)`로 치환 | 멱등성·위치 정확성. KNOU `embed_captures` 패턴 |
| **기능 플래그** | `ENABLE_FRAME_CAPTURE`, `FRAMES_PER_VIDEO` env | 비용·시간 통제, 끄면 기존 동작 그대로 |
| TDD 현실 적용 | 순수 로직만 단위테스트, yt-dlp/ffmpeg/비전은 수동 게이트 | 라이브 영상·AI는 단위테스트 비현실적 (KNOU와 동일 원칙) |

### 새/변경 파일
```
youtube-to-ebook/
├─ get_transcripts.py      # [변경] snippet.start 보존 → transcript_segments
├─ write_articles.py       # [변경] 기사 프롬프트에 [MM:SS] 마커 지시 + select_frame_moments()
├─ capture_frames.py       # [신규] yt-dlp+ffmpeg 프레임 추출 + 비전 선별
├─ export_archive.py       # [변경] upload_image_to_r2() + 마커→이미지 임베드
├─ send_email.py           # [변경] 이메일/EPUB 이미지 렌더 (선택, Phase 5)
├─ main.py                 # [변경] 캡처 단계 배선
├─ requirements.txt        # [변경] yt-dlp 추가
└─ docs/plans/PLAN_video-frame-capture.md  # 이 문서
```

---

## 3. Phases

### Phase 0 — 정찰 & 의존성 (1-2h)
**Goal**: yt-dlp로 샘플 영상의 스트림 URL을 얻고 ffmpeg로 특정 초의 프레임 1장을 실제로 뽑아본다. 스트림-seek vs 360p 다운로드 중 빠른 쪽을 실측 결정.

**Test Strategy**: 코드 거의 없음 → 수동 검증. `requirements.txt` 갱신만.

**Tasks**:
- [x] `requirements.txt`에 `yt-dlp` 추가 (설치본 2025.12.08)
- [x] 정찰 스크립트 `recon_frame.py`: 샘플 영상ID로 ①yt-dlp 포맷 목록 ②스트림 URL 추출 ③`ffmpeg -ss` URL seek ④다운로드 후 로컬 seek — 두 방식 소요시간 출력
- [x] **실행/검증**: `recon_frame.py` + 수동 ffmpeg로 out.jpg가 정상 프레임인지 확인 — `frame_120.jpg` = Steve Stoute 선명한 실제 화면(640×360, YAVG=180 밝음)
- [x] 결과를 본 문서 Notes에 기록(택한 방식, 추출 시간/장, 포맷코드)

**Quality Gate**:
- [x] 샘플 영상에서 ffmpeg가 정상 프레임 1장 추출(20KB, 검은화면 아님 — 시각 확인)
- [x] 채택 방식(다운로드-후-seek, android client) + 소요시간이 Notes에 기록됨
- [x] yt-dlp가 requirements에 명시됨

**Dependencies**: 없음
**Rollback**: `recon_frame.py` 삭제

---

### Phase 1 — 트랜스크립트 타임스탬프 보존 (1-2h)
**Goal**: 자막 세그먼트의 `start`(초)를 보존해 `video['transcript_segments'] = [{start, text}, ...]` 를 추가. 기존 `transcript`(이어붙인 텍스트)는 하위호환 유지.

**Test Strategy**: 세그먼트→타임스탬프 텍스트 포매터를 순수함수로 단위테스트.

**Tasks**:
- [x] **(RED)** `test_get_transcripts.py`:
  - `format_segments_with_timestamps(segments)` → `"[MM:SS] text..."` 라인들
  - `seconds_to_mmss(90)` → `"01:30"`, `seconds_to_mmss(3725)` → `"1:02:05"`
  - 빈 세그먼트 → 빈 문자열, 누락 키 방어
  - → 실패 확인(ImportError)
- [x] **(GREEN)** `get_transcripts.py`: `get_transcript`이 `(full_text, segments)` 반환, `result.snippets`에서 `(start, text)` 보존 → `video['transcript_segments']`. `transcript`는 그대로 유지.
- [x] **(REFACTOR)** 세그먼트 없을 때(실패 등) `transcript_segments=[]` 안전 처리, `getattr(s,'start',0)` 방어

**Quality Gate**:
- [x] `pytest test_get_transcripts.py` 통과 (10개)
- [x] 실제 영상 1편에서 `transcript_segments` 채워짐 — qi45Jl46Py8: **2445개** timed segments, `[00:00]/[00:02]/[00:03]` 정상
- [x] 기존 `transcript` 사용처 회귀 없음 — 전체 54개 통과(기존 44 + 신규 10)

**Dependencies**: Phase 0
**Rollback**: `get_transcripts.py` 변경 revert

---

### Phase 2 — 프레임 시점 선택 (Gemini 텍스트) (2-3h)
**Goal**: 기사 + 타임스탬프 세그먼트를 Gemini에 주고, 시각화 가치가 높은 **3~4개 시점**과 각 **캡션**을 JSON으로 받는다. 기사 본문에는 해당 위치에 `[[FRAME:MM:SS]]` 마커를 삽입.

**Test Strategy**: 프롬프트 빌더·JSON 파싱/salvage·타임스탬프 정규화·마커 삽입을 순수함수 단위테스트. 실제 AI 호출은 1편 수동 검증.

**Tasks**:
- [x] **(RED)** `test_frame_select.py`:
  - `build_frame_prompt(article, segments, n)` → "정확히 N개 / talking-head 회피 / JSON only / caption·anchor·timestamp" 지시 포함
  - `parse_frame_moments(text)` → `[{seconds,timestamp,caption,anchor}]`, 코드펜스/잘림 salvage (`_salvage_truncated_json` 재사용), 필수필드 누락·timestamp 오류 항목 drop
  - `clamp_and_dedupe(moments, duration, max_n, min_gap)` → 길이초과·음수 제거, 근접(±min_gap) 중복 제거, 정렬, 최대 N개
  - `inject_frame_markers(article_md, moments)` → anchor 단락 뒤 `[[FRAME:<seconds>]]` 삽입, anchor 없으면 문서 끝 갤러리
  - `_mmss_to_seconds` / mocked `select_frame_moments`(thinking_budget=0, 세그먼트 없으면 API 미호출)
  - → 실패 확인(ImportError)
- [x] **(GREEN)** `write_articles.py`에 위 함수들 + `select_frame_moments(video, article, n)` — thinking_budget=0, JSON 강제(요약 함수와 동일 안정화)
- [x] **(REFACTOR)** 마커 = 정수초 `[[FRAME:<seconds>]]`(MM:SS 재파싱·모듈결합 회피). 영문 기사 기준 1회 선정 → 이미지 언어중립이라 en/ko 공용

**Quality Gate**:
- [x] `pytest test_frame_select.py` 통과 (22개)
- [x] 실제 1편(qi45Jl46Py8)에서 **4개 시점+캡션 JSON 정상 산출** — 화면텍스트·그래픽(18% 통계)·해부 모형 등 talking-head 회피 확인, 캡션 구체적
- [x] 마커가 기사 마크다운에 삽입되고 본문 구조 안 깨짐(anchor 미스 시 갤러리 fallback 동작 확인)
- [x] 잘린 JSON·코드펜스 응답 salvage 됨(단위테스트)
- [x] 전체 회귀 76개 통과(기존 54 + 신규 22)

**Dependencies**: Phase 1
**Rollback**: `select_frame_moments`/마커 로직 제거

---

### Phase 3 — 🎞️ 프레임 추출 + 비전 선별 (3-4h) [핵심]
**Goal**: 선정된 시점마다 yt-dlp+ffmpeg로 후보 프레임 N장 추출 → Gemini 비전이 검은화면·전환장면 피해 1장 선택 → 로컬 jpg 확보.

**채택 방식**: Phase 0 실측에 따름(스트림-seek 또는 360p 1회 다운로드 후 로컬 seek). 후보창 = `VISION_OFFSETS=(-3,0,3,6)`초(자막↔화면 어긋남 보정).

**Test Strategy**: 파일명·ffmpeg 명령·후보오프셋·비전응답 파싱·needs_capture를 순수함수 단위테스트. 실제 추출/비전은 1편 수동.

**Tasks**:
- [x] **(RED)** `test_capture_frames.py`:
  - `frame_filename(video_id, seconds)` → `{video_id}_01-30.jpg` (sanitize)
  - `build_ffmpeg_cmd(src, sec, out)` → `-ss`가 `-i` 앞(fast seek), `-frames:v 1`, `-y`
  - `candidate_offsets(sec, duration)` → 음수/초과 클램프, 정각 항상 포함, dedupe
  - `build_vision_prompt(caption, n)` / `parse_vision_choice(text, n)` → index(범위초과/−1/깨짐=None, bare int 허용)
  - `needs_capture(path)` 없음/0바이트면 True
  - → 실패 확인(ModuleNotFound)
- [x] **(GREEN)** `capture_frames.py`: yt-dlp(android client, format 18)로 소스 1회 다운로드 → 시점마다 `candidate_offsets` ffmpeg 후보 추출(`_cand/`) → 인라인 바이트로 Gemini 비전 전송 → 픽 1장만 final로 이동. 비전 실패/−1 시 **정각 최근접 후보 fallback**.
- [x] **(REFACTOR)** 소스 1회 다운로드 후 전 시점 로컬 seek, 후보·소스mp4·`_cand`dir 정리, 시점별 try/except 격리, `needs_capture`로 재실행 skip

**Quality Gate**:
- [x] `pytest test_capture_frames.py` 통과 (24개)
- [x] 실제 1편(py5HZrVhG_c) 다운로드 5초 + 2시점 프레임 추출·비전 선별 완주, jpg 시각 확인(640×360, 검은화면 아님)
- [x] 비전이 후보 중 선명 프레임 선택(이 영상은 전편 talking-head라 회피불가 — 정상). 비전 실패 시 정각 fallback 경로 확인
- [x] 후보 없으면 그 시점만 skip, 소스 다운로드 실패 시 `{}` 반환(기사 무영향) — 실패 격리
- [x] 전체 회귀 100개 통과(기존 76 + 신규 24)

**Dependencies**: Phase 2(시점), Phase 0(방식)
**Rollback**: `capture_frames.py` 삭제, 임시 프레임 정리

---

### Phase 4 — R2 업로드 + 마크다운 임베드 (2-3h)
**Goal**: 추출 프레임을 R2에 올리고 공개 URL로 기사 마커 `[[FRAME:MM:SS]]` → `![caption](url)` 치환. 아카이브 발행에 통합.

**Test Strategy**: 업로드 키 빌더(mock)·마커 치환(멱등)·캡션 이스케이프를 단위테스트. 실제 업로드는 1편 수동.

**Tasks**:
- [x] **(RED)** `test_export_archive.py` 보강(8개):
  - `embed_frames(article_md, {seconds:(url,caption)})` → 마커를 `![caption](url)` + 가시 `*caption*` 으로 치환, 여러 마커, 맵 없는 마커 strip, 마커 없는 프레임 끝 갤러리, blank line collapse, 괄호 캡션 링크 보존
  - 프레임 없는 기사 → 마커만 깔끔히 제거(빈 `[[FRAME:..]]` 잔여 금지)
  - → 실패 확인(ImportError)
- [x] **(GREEN)** `export_archive.py`: `_upload_to_r2(path,key,ct)` 공유화 + `upload_image_to_r2`(key=`images/YYYY/MM/DD`, image/jpeg) + `embed_frames()` + `generate_issue_markdown(frame_map=)`에서 en/ko 본문 적용
- [x] **(REFACTOR)** `export_newsletter_issue(frame_data=)` → 프레임 R2 업로드 후 `frame_map` 빌드. R2 미설정 시 마커 strip만(로컬 경로 노출 0)

**Quality Gate**:
- [x] `pytest test_export_archive.py` 전체 통과 (30개: 기존 22 + 신규 8)
- [x] 통합 확인: `frame_map` 주입 시 발행 .md에 `![caption](url)` 인라인 + 가시 캡션, 원시 마커 0
- [x] R2 미설정 환경에서도 마커 잔여 없이 정상(빈 frame_map → strip) — 단위테스트 검증
- [x] 마커→이미지 1:1 치환이라 재실행/중복 삽입 없음(치환 후 마커 소멸)
- [x] 전체 회귀 108개 통과(기존 100 + 신규 8)

**Dependencies**: Phase 3
**Rollback**: `export_archive.py` 변경 revert

---

### Phase 5 — 파이프라인 배선 + 이메일/EPUB (2-3h)
**Goal**: `main.py`에 캡처 단계를 끼워 전체 흐름 완성하고, 이메일 HTML·EPUB에도 이미지 노출.

**Test Strategy**: 단계 on/off·실패 격리 로직 단위테스트. 전체 흐름은 1편 수동 스모크.

**Tasks**:
- [ ] **(GREEN)** `main.py`: [STEP 3] 기사 생성 후 → 시점선택(Phase2) → 프레임추출(Phase3) → 기사에 마커 주입. `ENABLE_FRAME_CAPTURE` 꺼지면 전부 skip(기존 동작 동일).
- [ ] `send_email.py`: 마크다운 이미지가 HTML/EPUB에서 `<img>`로 렌더되는지 확인(이미 markdown 변환 경로 통과 — R2 절대 URL이라 이메일에서도 표시)
- [ ] 기능 플래그·`FRAMES_PER_VIDEO` env 문서화(README/CLAUDE.md)
- [ ] **(REFACTOR)** 캡처 단계 try/except로 전체 실패 격리(캡처 죽어도 다이제스트는 발행)

**Quality Gate**:
- [ ] `pytest` 전체 통과
- [ ] 1편 엔드투엔드 스모크: 기사+요약+3~4 인라인 이미지가 아카이브에 발행됨
- [ ] `ENABLE_FRAME_CAPTURE=false`면 기존과 100% 동일 동작(회귀 0)
- [ ] 캡처 단계 강제 실패 주입 시에도 다이제스트 정상 발행
- [ ] 문서 갱신(README/CLAUDE.md에 새 env·동작 기재)

**Dependencies**: Phase 4
**Rollback**: `main.py`에서 캡처 단계 호출 제거(플래그 off로도 무력화)

---

## 4. Risk Assessment

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| yt-dlp가 봇 차단/포맷 변경으로 실패 | Med | High | Phase 0 실측, 실패 시 캡처만 skip하고 기사 발행(격리). yt-dlp 버전 고정 |
| 스트림 seek 느림/타임아웃 | Med | Med | Phase 0에서 360p 1회 다운로드 방식과 비교해 빠른 쪽 채택 |
| 자막 시점 ≠ 화면 시점 어긋남 | High | Med | 비전 후보창(±오프셋)으로 보정(KNOU 6.5 실증) |
| 검은화면/전환장면 프레임 | Med | Med | 비전 선별 + t정각 fallback |
| Gemini 비전 비용 누적 | Low | Low | 영상당 3~4 시점×후보 4장 ≈ $0.02/영상. 플래그로 통제 |
| R2 용량/비용 증가 | Low | Low | jpg 압축, key 날짜 경로, 미설정 시 graceful skip |
| 이메일 클라이언트가 외부 이미지 차단 | Med | Low | R2 절대 URL + alt 텍스트(캡션). 차단돼도 캡션은 보임 |
| 처리시간 증가(영상당 추출) | Med | Med | 플래그·장수 제한, 야간 실행이면 영향 낮음 |

> ⚠️ **저작권/이용 참고**: 추출 프레임은 개인 학습·요약 다이제스트 맥락의 인용. 공개 재배포 범위는 사용자 책임 영역.

---

## 5. Progress Tracking

| Phase | 상태 | 완료일 |
|-------|------|--------|
| 0. 정찰 & 의존성 | ✅ 완료 | 2026-05-27 |
| 1. 트랜스크립트 타임스탬프 보존 | ✅ 완료 | 2026-05-27 |
| 2. 프레임 시점 선택(Gemini) | ✅ 완료 | 2026-05-27 |
| 3. 프레임 추출 + 비전 선별 | ✅ 완료 | 2026-05-27 |
| 4. R2 업로드 + 마크다운 임베드 | ✅ 완료 | 2026-05-27 |
| 5. 파이프라인 배선 + 이메일/EPUB | ⬜ 대기 | - |

상태 범례: ⬜ 대기 / 🔄 진행중 / ✅ 완료 / ⚠️ 막힘

---

## 6. Notes & Learnings

> 각 Phase 진행하며 배운 점, 막힌 점, 영상/도구 특이사항을 여기에 기록.

- (환경 사전확인) ffmpeg 8.0.1 설치됨, yt-dlp 2025.12.08 Python 모듈(`py -m yt_dlp`) 가용. R2 업로드 인프라는 `export_archive.upload_audio_to_r2`에 이미 존재 → 이미지용으로 일반화.
- (설계) 참고: KNOU LMS 자동화 계획의 Phase 5/6/6.5 — 타임스탬프 정규화·클립 타임라인·비전 후보 선별(`VISION_OFFSETS`, `parse_vision_choice`, `embed_captures` 멱등 치환)이 검증된 패턴. YouTube는 DRM 없음 → PDF 슬라이드 fallback 불필요(KNOU와 차이).
- (Phase 0 실측 ✅) **🔑 핵심 발견 — 기본 'web' client는 403**: yt-dlp 기본(web) client는 DASH/AV1 video-only URL을 주는데 ffmpeg/yt-dlp가 받으려 하면 **HTTP 403 Forbidden**. 스트림-seek 방식(Strategy A) 완전 실패. **해결 = `extractor_args={'youtube':{'player_client':['android']}}`** → 클래식 **format 18**(360p progressive, H.264+AAC, 단일 mp4) 제공 → 깔끔히 다운로드됨.
- (Phase 0 실측 ✅) **채택 = 다운로드-후-로컬-seek**(Strategy B). py5HZrVhG_c(6.5분): format 18 = 15.3MB **~7초** 다운로드 → 이후 `ffmpeg -ss {sec} -i file.mp4 -frames:v 1`는 **프레임당 사실상 즉시**(<0.1s). 영상당 1회 다운로드로 3~4장 전부 로컬 추출 → Phase 3은 이 방식 확정.
- (Phase 0 실측 ✅) **프레임 품질 양호**: 640×360, ~20KB/jpg, `frame_120.jpg` 시각 확인 = 화자 선명. **단 talking-head 위주**(흰 배경+인물) → Phase 2의 시각화 가치 시점 선정 + Phase 3 비전 선별로 정적 화면 회피 필요성 실증.
- (Phase 0 메모) ffmpeg는 `-ss`를 `-i` 앞에 둬야 fast input seek. 검은화면 판별은 `signalstats` YAVG(밝기)로 가능(여기선 180 = 밝음). `-f null -` + metadata print로 측정.
- (Phase 1 실측 ✅) `get_transcript`을 `(full_text, segments)` 튜플 반환으로 변경, `segments=[{start,text}]`. `snippet.start`는 그대로 살아있어 보존 손쉬움. qi45Jl46Py8 라이브 = **2445 timed segments**, `[MM:SS] text` 렌더 정상. 호출처는 `get_transcripts.py` 내부 2곳뿐이라 영향 국소적. 순수함수 `seconds_to_mmss`(음수 클램프·float floor·1h+ 시 H:MM:SS)/`format_segments_with_timestamps`(blank skip·키 누락 방어) 단위테스트 10개.
- (Phase 2 실측 ✅) `select_frame_moments`가 기사+타임스탬프 트랜스크립트를 flash(thinking_budget=0)에 주고 JSON 산출. qi45Jl46Py8 라이브: **4시점** 모두 시각가치 높음(화면텍스트로 화자 권위표시, 혜택 그래픽, "18%" 통계 그래픽, 음핵 플러시 모형) — talking-head 회피 성공. **마커 = 정수초 `[[FRAME:<seconds>]]`** (Phase 4 단순 치환·모듈결합 회피). prompt 토큰 ≈ 42k(2445세그 전체 포함) — flash라 비용 미미하지만 매우 긴 영상은 후속 모니터.
- (Phase 2 주의) **anchor 매칭은 best-effort**: 모델이 anchor를 트랜스크립트에서 뽑으면 기사에 없어 갤러리 fallback로 감(throwaway 기사 테스트에서 4/4 fallback 관측). 실파이프라인은 기사·프레임이 같은 트랜스크립트 기반이라 매칭률↑. fallback이 마커 유실 막음(검증됨). 필요 시 Phase 5에서 anchor를 기사 본문 기준으로 재선정하도록 프롬프트 강화 검토.
- (Phase 3 실측 ✅) **다운로드-후-로컬-seek** 확정 동작: py5HZrVhG_c 16MB **~5초** 다운로드 → 시점당 후보 4장(`VISION_OFFSETS=(-2,0,3,6)`) ffmpeg 추출 → Gemini 비전(thinking_budget=0, temp=0.1)에 인라인 바이트 전송 → `parse_vision_choice`로 0-based index 픽 → final 이동. **비전 실패/−1 시 정각 최근접 후보 fallback**. `types.Part.from_bytes(data, mime_type)`로 이미지 전송.
- (Phase 3 정리) 처리 후 소스 mp4(16MB)·후보 jpg·`_cand`dir 제거(재실행 시 디스크 누적 방지). `needs_capture`로 이미 있는 final은 skip. `frames/`는 .gitignore. 시점별 try/except로 한 프레임 실패가 나머지·기사에 영향 없음. 소스 다운로드 실패 시 `{}` 반환.
- (Phase 3 관찰) talking-head 일변도 영상은 비전도 인물샷밖에 못 고름(정상 한계). 슬라이드·그래픽 많은 채널(예: 강연·튜토리얼)에서 비전 선별 효과가 큼 — Phase 5 라이브에서 다양한 채널로 추가 관찰 예정.
- (Phase 4 실측 ✅) `embed_frames(article_md, {sec:(url,caption)})`: `[[FRAME:<sec>]]` → `![caption](url)` + 가시 `*caption*`. 맵에 없는 마커(추출/업로드 실패분)는 strip해 **원시 마커 절대 미노출**. 맵엔 있는데 마커 없는 프레임은 끝 갤러리. blank line collapse. 마커→이미지 1:1이라 재실행 중복 0. R2 업로더는 `_upload_to_r2(path,key,ct)` 공유화 후 audio/image 분기, key=`images/YYYY/MM/DD/`. `export_newsletter_issue(frame_data={sec:(local,caption)})`가 업로드→frame_map 빌드→`generate_issue_markdown(frame_map=)`. R2 미설정 시 frame_map={} → 마커 strip만(로컬경로 0노출).
