# FORSLOWDIVE.md

> "유튜브 영상을 이북으로? 그게 돼?"
> 네, 됩니다. 이 문서는 그 여정의 기록입니다.

---

## 이 프로젝트가 하는 일

**YouTube to Ebook**은 유튜브 영상을 잡지 스타일의 EPUB 이북으로 변환합니다.

당신이 구독하는 유튜브 채널의 최신 영상을 가져와서, 자막을 추출하고, AI가 읽기 좋은 기사로 재작성한 뒤, 영어/한국어 두 버전의 뉴스레터를 이메일로 보내줍니다. EPUB 파일이 첨부되어 있어서 킨들이나 스마트폰 이북 앱에서 바로 읽을 수 있습니다.

**한 줄 요약**: 출퇴근길에 유튜브 영상을 "읽을 수" 있게 해주는 도구입니다.

---

## 아키텍처: 조립 라인처럼 흘러가는 파이프라인

이 프로젝트는 공장의 조립 라인처럼 동작합니다. 원자재(영상)가 들어가면 완제품(이북)이 나옵니다.

```
+---------------+     +------------------+     +-----------------+     +-------------+
|  get_videos   | --> | get_transcripts  | --> |  write_articles | --> |  send_email |
+---------------+     +------------------+     +-----------------+     +-------------+
        |                     |                        |                      |
        v                     v                        v                      v
   YouTube API      youtube-transcript-api        Gemini AI            Gmail SMTP
   (채널 영상)           (자막 추출)             (기사 생성)          (EPUB + 이메일)
```

**각 단계의 역할:**

| 단계 | 파일 | 하는 일 | 딜레이 |
|------|------|---------|--------|
| 1 | `get_videos.py` | 채널별 최신 영상 목록 가져오기 | - |
| 2 | `get_transcripts.py` | 영상 자막 텍스트 추출 | 7초 |
| 3 | `write_articles.py` | AI가 자막을 기사로 변환 | 15초 |
| 4 | `send_email.py` | HTML/EPUB 생성 후 이메일 발송 | - |

**main.py**가 지휘자 역할을 합니다. 각 단계를 순서대로 호출하고, **video_tracker.py**를 통해 이미 처리한 영상은 건너뛰도록 합니다.

### 왜 이런 구조인가?

처음에는 하나의 거대한 스크립트로 시작했습니다. 금방 스파게티가 되었죠. 디버깅할 때 "자막 추출에서 문제인가, AI 호출에서 문제인가?"를 구분하기 어려웠습니다.

그래서 **단일 책임 원칙**을 적용했습니다:
- 각 파일은 딱 한 가지 일만 합니다
- 각 파일은 독립적으로 테스트할 수 있습니다 (`python get_videos.py`로 단독 실행 가능)
- 문제가 생기면 어디가 문제인지 즉시 알 수 있습니다

---

## 파일별 상세 설명

### `main.py` — 지휘자

모든 것을 조율합니다. 마치 오케스트라 지휘자처럼, 각 섹션(파일)이 언제 연주해야 하는지 알려줍니다.

```python
# 파이프라인의 흐름
videos = fetch_videos()           # 1. 영상 목록 가져오기
new_videos = filter_new_videos()  # 1b. 이미 처리한 건 제외
transcripts = get_transcripts()   # 2. 자막 추출
articles = write_articles()       # 3. AI로 기사 작성
send_newsletter()                 # 4. 이메일 발송
mark_videos_processed()           # 5. 처리 완료 기록
```

**특별한 기능**: `--url` 플래그로 특정 영상 하나만 처리할 수 있습니다. 이 경우 채널 목록과 처리 기록을 무시하고, "심층 분석 모드"로 더 자세한 기사를 생성합니다.

### `get_videos.py` — 정찰병

YouTube API를 사용해 각 채널의 최신 영상을 찾아옵니다.

**핵심 인사이트**: 유튜브 검색 API는 믿을 수 없습니다. 최신 영상이 검색 결과에 안 나올 때가 많아요. 대신 **uploads playlist**를 사용합니다. 모든 채널에는 업로드 순서대로 정렬된 숨겨진 플레이리스트가 있거든요.

```python
# 검색 API 대신 업로드 플레이리스트 사용
uploads_playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
```

**Shorts 감지의 함정**: 처음에는 영상 길이로 Shorts를 구분하려 했습니다 (60초 미만 = Shorts). 틀렸습니다! 어떤 Shorts는 60초를 넘습니다. 정확한 방법은 `/shorts/` URL로 HEAD 요청을 보내는 것입니다.

```python
def is_youtube_short(video_id):
    shorts_url = f"https://www.youtube.com/shorts/{video_id}"
    response = requests.head(shorts_url, allow_redirects=True)
    return "/shorts/" in response.url  # 리다이렉트 안 되면 Shorts
```

### `get_transcripts.py` — 속기사

유튜브 자막을 텍스트로 추출합니다.

**함정 주의**: `YouTubeTranscriptApi`의 클래스 메서드가 deprecated되었습니다. 인스턴스를 만들어서 사용해야 합니다:

```python
# 잘못된 방법 (deprecated)
transcript = YouTubeTranscriptApi.get_transcript(video_id)

# 올바른 방법
ytt_api = YouTubeTranscriptApi()
transcript = ytt_api.fetch(video_id)
```

**Rate Limiting**: 7초 딜레이를 넣었습니다. 너무 빠르게 요청하면 유튜브가 IP를 차단합니다. VPN을 쓰거나 잠시 기다리면 풀립니다.

### `write_articles.py` — 작가

Google Gemini AI가 자막을 매거진 스타일 기사로 변환합니다.

**프롬프트 엔지니어링**: 이 파일의 핵심은 프롬프트입니다. 단순히 "기사로 만들어줘"라고 하면 위키피디아 같은 딱딱한 글이 나옵니다. 우리는 구체적인 가이드라인을 줍니다:

```python
style_guide = """매거진 스타일의 기사를 작성하세요.

## 가독성 (최우선)
- 한국어로 자연스럽게 읽히는 문장을 우선하세요
- 복잡한 개념은 쉬운 비유나 예시로 풀어서 설명하세요
...

## 전문 용어 처리
- 전문 용어는 한글 번역과 영어를 병기하세요 (예: 강화학습(Reinforcement Learning))
...
```

**Rate Limiting의 중요성**: Gemini API는 분당 요청 수 제한이 있습니다. 15초 딜레이와 3회 재시도 로직을 넣었습니다. 429 에러(Too Many Requests)가 나면 30초 기다렸다가 다시 시도합니다.

### `send_email.py` — 배달부

완성된 기사를 HTML 뉴스레터와 EPUB 이북으로 만들어 이메일로 보냅니다.

**EPUB 생성**: `ebooklib`을 사용합니다. EPUB은 본질적으로 ZIP 파일 안에 HTML들이 들어있는 구조입니다. 목차(NCX)와 네비게이션(NAV)을 추가해야 제대로 된 이북으로 인식됩니다.

```python
book.toc = tuple(chapters)      # 목차 설정
book.add_item(epub.EpubNcx())   # NCX 네비게이션
book.add_item(epub.EpubNav())   # NAV 네비게이션
book.spine = ["nav"] + chapters # 읽는 순서
```

### `video_tracker.py` — 기억력

JSON 파일로 처리한 영상 목록을 관리합니다. 간단하지만 필수적입니다. 이게 없으면 매번 같은 영상을 반복 처리하게 됩니다.

### `dashboard.py` — 관제탑

Streamlit으로 만든 웹 대시보드입니다. 채널 관리, 프롬프트 수정, 뉴스레터 생성, 아카이브 열람이 가능합니다.

**디자인 철학**: "에디토리얼 매거진" 미학을 추구했습니다. 다크 모드, 골드 액센트, Cormorant Garamond 폰트를 사용해 고급스러운 느낌을 줍니다.

---

## 사용된 기술과 선택 이유

| 기술 | 역할 | 왜 이걸 선택했나 |
|------|------|-----------------|
| **google-api-python-client** | YouTube API | 공식 라이브러리. 안정적이고 문서화가 잘 되어 있음 |
| **youtube-transcript-api** | 자막 추출 | YouTube Data API로는 자막을 못 가져옴. 이 라이브러리가 유일한 선택지 |
| **google-genai** | Gemini AI | 한국어 품질이 좋고, 무료 티어가 넉넉함 |
| **ebooklib** | EPUB 생성 | 파이썬에서 EPUB 만드는 표준 라이브러리 |
| **markdown** | HTML 변환 | Gemini가 마크다운으로 출력하므로 HTML로 변환 필요 |
| **streamlit** | 웹 대시보드 | 파이썬만으로 빠르게 웹 UI 구축 가능 |

---

## 배운 교훈들

### 버그와의 전쟁

#### 1. Windows 콘솔 인코딩 지옥

**증상**: 한글이 `?????`로 나오거나 `UnicodeEncodeError` 발생

**원인**: Windows 콘솔의 기본 인코딩이 UTF-8이 아님

**해결**:
```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
```

모든 파이썬 파일 상단에 이 코드를 넣었습니다. `errors='replace'`는 인코딩 불가능한 문자를 `?`로 대체해서 크래시를 방지합니다.

#### 2. API Rate Limiting

**증상**: 갑자기 429 에러가 터지면서 전체 파이프라인 실패

**교훈**: 외부 API를 호출할 때는 항상 딜레이와 재시도 로직을 넣으세요. "내 컴퓨터에서는 잘 되는데"는 무의미합니다.

```python
REQUEST_DELAY = 15  # 요청 사이 대기
MAX_RETRIES = 3     # 최대 재시도 횟수
RETRY_DELAY = 30    # 에러 시 대기 시간
```

#### 3. 유튜브 검색 API의 배신

**증상**: 분명히 어제 올라온 영상인데 검색 결과에 안 나옴

**교훈**: 검색 API는 "검색"용이지 "최신 영상 조회"용이 아닙니다. 정확한 시간순 정렬이 필요하면 uploads playlist를 사용하세요.

### 피해야 할 함정들

1. **자막이 없는 영상**: 일부 영상은 자막이 비활성화되어 있습니다. 이런 영상은 건너뛰어야 합니다.

2. **너무 긴 트랜스크립트**: 8000단어 이상의 자막은 잘라냅니다. AI 토큰 제한과 비용 때문입니다.

3. **Shorts 감지**: 영상 길이로 판단하지 마세요. `/shorts/` URL 패턴을 확인하세요.

4. **이메일 발송 실패 후 처리 기록**: 이메일 발송이 성공한 경우에만 `mark_videos_processed()`를 호출합니다. 그렇지 않으면 영상이 "처리됨"으로 표시되지만 실제로는 뉴스레터가 안 갔을 수 있습니다.

### 좋은 엔지니어가 생각하는 방식

#### 1. 실패를 가정하라
모든 외부 호출(API, 파일, 네트워크)은 실패할 수 있다고 가정합니다. try-except로 감싸고, 의미 있는 에러 메시지를 출력합니다.

#### 2. 디버그 로그를 아끼지 마라
```python
print(f"[DEBUG] Starting run() function...", flush=True)
print(f"[{i+1}/{len(videos)}] {video['title'][:50]}...")
```
`flush=True`는 버퍼링 없이 즉시 출력합니다. 크래시 직전에 무슨 일이 있었는지 알 수 있습니다.

#### 3. 단독 실행 가능하게 만들어라
```python
if __name__ == "__main__":
    # 이 파일만 단독 실행할 때의 테스트 코드
```
모든 파일에 이 패턴을 넣었습니다. 디버깅할 때 전체 파이프라인을 돌릴 필요 없이 해당 파일만 테스트할 수 있습니다.

#### 4. 설정은 상단에 모아라
```python
REQUEST_DELAY = 15
MAX_RETRIES = 3
RETRY_DELAY = 30
```
매직 넘버를 코드 중간에 숨기지 마세요. 상단에 상수로 정의하면 나중에 튜닝하기 쉽습니다.

---

## 베스트 프랙티스 체크리스트

- [x] **환경변수로 시크릿 관리**: API 키를 코드에 직접 넣지 않음 (`.env` 사용)
- [x] **단일 책임 원칙**: 각 파일이 한 가지 역할만 수행
- [x] **방어적 프로그래밍**: 모든 외부 호출에 에러 핸들링
- [x] **진행 상황 표시**: 사용자가 뭐가 진행되고 있는지 알 수 있도록
- [x] **멱등성**: 같은 영상을 두 번 처리하지 않음 (video_tracker)
- [x] **플랫폼 호환성**: Windows/Mac 모두에서 동작 (인코딩 처리)

---

## 마무리

이 프로젝트는 "자동화"의 힘을 보여줍니다.

매일 아침 유튜브를 뒤지며 "어떤 영상을 볼까" 고민하는 대신, 잠자는 동안 AI가 기사로 정리해서 이메일로 보내줍니다. 출퇴근길에 스마트폰으로 읽으면 됩니다.

기술적으로는 단순합니다. YouTube API, 자막 추출, AI 글쓰기, 이메일 발송. 각각은 어렵지 않습니다. 하지만 이것들을 **파이프라인으로 엮어서 자동화**하는 것, 그리고 **실패에 대비하는 것**이 진짜 엔지니어링입니다.

> "좋은 코드는 동작하는 코드다. 위대한 코드는 실패해도 우아하게 실패하는 코드다."

---

*이 문서는 YouTube to Ebook 프로젝트의 기술적 여정을 기록합니다. 질문이 있다면 코드를 읽어보세요. 코드는 거짓말을 하지 않습니다.*
