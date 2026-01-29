# YouTube to Ebook (AI 뉴스레터 버전)

좋아하는 유튜브 채널의 영상들을 보기 좋은 매거진 스타일의 **AI 뉴스레터**로 받아보세요. 

> **ℹ️ 참고:** 이 프로젝트는 [zarazhangrui/youtube-to-ebook](https://github.com/zarazhangrui/youtube-to-ebook)을 기반으로 수정되었습니다.
> *   **🤖 AI 변경:** Claude(앤쓰로픽) 대신 **Google Gemini(제미나이)**를 사용하여 비용 접근성을 높였습니다.
> *   **🇰🇷 한글 지원:** 영상 내용을 자연스러운 한국어 기사로 요약/변환하여 이메일로 발송합니다.

---

## 🚀 시작하기 (초보자 가이드)

개발자가 아니어도 괜찮습니다! 아래 순서대로 천천히 따라 해보세요.

### 1단계: 필수 프로그램 설치
이 프로그램을 돌리려면 **Python(파이썬)**과 **Git(깃)**이 필요합니다.
*   **Git 설치:** [git-scm.com](https://git-scm.com/downloads)에서 다운로드 후 설치 (기본 설정 그대로 'Next'만 눌러도 됩니다).
*   **Python 설치:** [python.org](https://www.python.org/downloads/)에서 다운로드 후 설치 (**중요:** 설치 첫 화면에서 `Add Python to PATH` 체크박스를 꼭 켜주세요!)

### 2단계: 내 컴퓨터로 다운로드
1. 컴퓨터에서 명령 프롬프트(cmd)나 터미널을 엽니다.
   * *윈도우 키 + R 입력 → `cmd` 입력 후 엔터*
2. 프로그램을 저장할 폴더(예: 문서 폴더)로 이동한 후, 아래 명령어를 순서대로 입력하여 다운로드합니다:
   ```bash
   cd Documents
   git clone https://github.com/slowdive14/youtube-to-ebook.git
   cd youtube-to-ebook
   ```
3. 필요한 라이브러리를 설치합니다:
   ```bash
   pip install -r requirements.txt
   ```

### 3단계: 구글 제미나이(Gemini) API 키 발급
이 프로그램은 구글의 인공지능을 사용하므로 열쇠(API Key)가 필요합니다.
1. [Google AI Studio](https://aistudio.google.com/app/apikey)에 접속합니다.
2. 구글 계정으로 로그인합니다.
3. **"Create API key"** 버튼을 누릅니다.
4. 생성된 키(문자열)를 복사해둡니다. (누구에게도 보여주지 마세요!)

### 4단계: 설정 파일 만들기
1. 다운로드 받은 폴더(`youtube-to-ebook`) 안에 `.env.example`이라는 파일이 있습니다.
2. 이 파일의 이름을 `.env`로 바꿉니다. (뒤에 `.example`을 지우세요)
3. 메모장으로 `.env` 파일을 엽니다.
4. 아까 복사한 키를 `GEMINI_API_KEY=` 옆에 붙여넣습니다. `your_api_key_here` 부분은 지우세요.
5. **유튜브 API 키(필수):** [구글 클라우드 콘솔](https://console.cloud.google.com/)에서 `YouTube Data API v3`를 직접 활성화하고 키를 발급받아 `YOUTUBE_API_KEY`에 넣어야 합니다. 이 키가 있어야 프로그램이 자동으로 최신 영상을 찾아올 수 있습니다. (발급 방법은 인터넷 검색을 활용하면 쉽게 찾을 수 있습니다!)
6. **이메일로 받아보기:** .env 파일 아래쪽 `GMAIL_ADDRESS`에 본인 지메일 주소를, `GMAIL_APP_PASSWORD`에는 지메일 비밀번호 대신 **[앱 비밀번호](https://myaccount.google.com/apppasswords)**를 발급받아 넣으세요. (이메일로 받고 싶지 않다면 비워두세요)

### 5단계: 채널 추가하고 실행하기
1. `channels.txt` 파일을 메모장으로 열고, 요약하고 싶은 유튜버의 핸들(골뱅이 아이디)을 한 줄에 하나씩 적습니다.
   예시:
   ```text
   @hubermanlab
   @DrChatterjeeRangan
   ```
2. 이제 실행합니다! 터미널(cmd)에서:
   ```bash
   python main.py
   ```
*(참고: 윈도우에서 `python` 명령어가 안 되면 `py main.py`라고 입력해 보세요!)*

🎉 **완료!** 잠시 기다리면 지정한 이메일로 뉴스레터가 도착합니다. 스마트폰이나 PC에서 편하게 읽어보세요.

---

## ✨ 새로운 기능 (강력 추천!)

### 🔍 심층 분석 모드 (기본 적용)
이제 모든 뉴스레터(정기 발송 포함)에 **심층 분석 모드**가 기본으로 적용됩니다. 단순 요약을 넘어 콘텐츠의 핵심 메시지, 데이터, 구체적 사례를 상세히 분석하여 더 깊이 있는 기사를 생성합니다.

*특정 영상 하나만 즉시 분석하고 싶을 때도 동일하게 이 모드가 사용됩니다:*
   ```bash
   python main.py --url "https://www.youtube.com/watch?v=영상ID"
   ```

### ⏰ 매일 자동으로 실행하기 (자동화)
매번 직접 실행하기 귀찮으시죠? 컴퓨터가 알아서 매일 한 번씩 새로운 영상을 체크하도록 설정할 수 있습니다.
*   **윈도우 전용:** 폴더 안의 `run_daily.bat` 파일을 마우스 우클릭하여 '바탕화면에 바로가기'를 만들거나, 윈도우 '작업 스케줄러'에 등록하세요.
*   **맥(Mac) 전용:** `run_newsletter.sh`와 `com.youtube.newsletter.plist`를 활용하여 LaunchAgent로 등록하면 정해진 시간에 자동으로 돌아갑니다.

---

## 🙋 자주 묻는 질문 & 문제 해결

### Q. `Too Many Requests` 혹은 `429` 에러가 떠요.
무료 버전의 제미나이 API를 사용하면 **사용량 제한**이 있습니다.
*   **해결책 1:** 프로그램이 자동으로 기다렸다가 다시 시도하도록 설정되어 있습니다. 터미널을 끄지 말고 조금만 기다려주세요.
*   **해결책 2:** 만약 계속 막힌다면, 잠시 VPN을 켜서 IP를 바꿔서 시도해보는 것도 방법입니다.
*   **해결책 3:** 한 번에 너무 많은 영상을 처리하려고 하면 걸릴 수 있습니다. `channels.txt`에 채널을 1개만 남기고 시도해보세요.

### Q. 유튜브 쇼츠(Shorts)도 포함되나요?
아니요, 쇼츠는 내용 요약에 적합하지 않아 자동으로 제외됩니다.

### Q. 이미 다 본 영상이 또 나오나요?
아니요, 프로그램이 이미 처리한 영상은 기억해두었다가 건너뜁니다. 새로운 영상만 골라서 책으로 만들어줍니다.
