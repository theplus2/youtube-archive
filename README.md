# youtube-archive

유튜브 영상의 자막을 추출해 14대 카테고리로 분류하고, 서식이 적용된 구글 문서로
Google Drive `YouTube지식 통합아카이빙` 폴더에 저장하는 Claude Code 스킬 저장소.

## 사용법

이 저장소를 연 Claude Code 세션에서 유튜브 URL과 함께 요청한다.

```
https://www.youtube.com/watch?v=... 요약해서 아카이빙해줘        ← Mode B (기본)
https://youtu.be/... 전문 텍스트로 정리해줘                     ← Mode A
https://youtu.be/... 전문과 시각화 자료 둘 다                   ← 듀얼
https://www.youtube.com/playlist?list=... 재생목록 전체 아카이빙해줘 ← 영상마다 문서 1개
```

재생목록은 영상 목록을 먼저 받아 처리할 영상 수와 이미 아카이빙된 영상을 알려 준 뒤, 확인을 받고 영상마다 문서를 하나씩 만든다.

필요 조건: Google Drive 커넥터 연결, 네트워크 정책이 `youtube.com` · `pypi.org` · `generativelanguage.googleapis.com` 허용.
선택: `watch` 스킬 + 환경 설정에 `GEMINI_API_KEY` 등록(YouTube 차단 시 Gemini가 대신 받아쓰기).

## 로컬 PC에서 실행 (권장)

클라우드 세션은 YouTube가 데이터센터 IP를 봇으로 차단해 자막을 거의 받지 못한다.
가정·교회 인터넷에서는 원문 자막을 바로 받을 수 있으므로 **로컬 실행을 기본으로 한다.**

1. Python 3.10 이상, Git, [Claude Code](https://code.claude.com) 설치
2. yt-dlp용 JavaScript 런타임 설치: [Deno](https://deno.com) 권장 (Node.js도 동작)
3. 저장소 받기

```bash
git clone -b claude/blissful-goldberg-u0xk3q https://github.com/theplus2/youtube-archive.git
```

```bash
cd youtube-archive
```

```bash
pip install -r requirements.txt
```

4. 이 폴더에서 Claude Code를 열고, Google Drive 커넥터가 연결되어 있는지 확인한다
   (claude.ai 계정으로 로그인하면 claude.ai에 연결한 커넥터를 쓸 수 있다).
5. 유튜브 URL과 함께 "요약해서 아카이빙해줘"라고 요청한다.

- Windows에서는 명령의 `python3`를 `py`로 바꿔 실행한다(`pip install`은 `py -m pip install`).
  `python`은 Microsoft Store 바로가기라 실행되지 않을 수 있다.
- 자막 트랙이 없는 영상만 Whisper 계열 전사가 필요하다(`watch` 스킬의 WhisperX 등).
- Gemini 경로는 선택 사항이다. 쓰려면 `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` 환경 변수를 설정한다.

## 구조

| 경로 | 역할 |
| :--- | :--- |
| `.claude/skills/youtube-archive/SKILL.md` | 워크플로와 규칙 (Claude가 읽는 지침) |
| `scripts/yt_fetch.py` | 메타데이터·자막 추출 → `work/<ID>/` |
| `scripts/clean_transcript.py` | 전문 교정: 자막 청크 분할(`prep`) · 교정본 누락 검사(`check`) |
| `scripts/build_doc.py` | `content.json` → 서식이 고정된 `doc.html` |
| `config/categories.json` | 14대 카테고리, Drive 폴더 ID 캐시 |
| `work/` | 작업 산출물 (git 제외) |

## 수동 실행

```bash
pip install -r requirements.txt
```

```bash
python3 scripts/yt_fetch.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

```bash
python3 scripts/build_doc.py work/VIDEO_ID
```

```bash
python3 scripts/yt_fetch.py --list "https://www.youtube.com/playlist?list=LIST_ID"   # 재생목록 → work/playlist_<ID>.json
```

## 알려진 한계

- **자막 추출은 클라우드 IP에서 불안정하다.** YouTube가 봇 차단(403/429, "Sign in to confirm")을 건다.
  이때 `watch` 스킬의 Gemini 엔진이 대신 받아쓴다(키 필요). 이것도 안 되면 유튜브의 "스크립트 표시"
  텍스트를 붙여넣어 `--transcript-file`로 넘긴다.
- **Gemini 받아쓰기는 원문 자막이 아니다.** 누락·오기·환각이 있을 수 있어 문서에 경고가 자동 표기된다.
  긴 영상은 20분 단위로 나눠 받아쓰며, 구간 경계에서 문장이 끊기거나 겹칠 수 있다.
- 자동 생성 자막은 고유명사·전문용어 오인식이 있다. 전문은 Claude가 문맥으로 교정하지만 완벽하지 않으므로,
  확신 없는 곳은 `(?)`·`[불명확]`으로 남기고 문단마다 원본 영상 시각 링크를 단다.
- HTML → Google Docs 변환은 Drive가 수행하며 일부 CSS는 유실될 수 있다.
