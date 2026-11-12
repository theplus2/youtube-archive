---
name: youtube-archive
description: "[v5.1.0] 유튜브 영상의 자막을 추출해 14대 카테고리로 분류하고, 서식이 적용된 구글 문서로 드라이브 'YouTube지식 통합아카이빙' 폴더에 저장한다. 사용자가 유튜브 URL을 주며 정리·요약·전문·아카이빙·분석을 요청할 때 사용한다. 전문(Mode A) / 시각화 요약(Mode B, 기본) / 듀얼 모드 지원."
---

# 유튜브 텍스트 추출·분석 아카이빙 (Claude Code + GitHub 저장소판)

## Version Build Log

- v1.0.0 ~ v4.5.0: 7→14대 카테고리, 듀얼 모드, HTML/CSS 변환 엔진, 파일명/폴더명 분리 (이전 환경용)
- **v5.0.0**: Claude Code 클라우드 세션 + 이 저장소 기준으로 재구현.
  - 존재하지 않는 `youtube:get_video_information` → `scripts/yt_fetch.py` (yt-dlp → youtube-transcript-api 순 폴백)
  - 서식을 프롬프트 규칙에서 **코드(`scripts/build_doc.py`)로 이전**: 글꼴·정렬·딥링크·파일명 규칙을 스크립트가 고정
  - 전문(Mode A) 본문은 자막 원본에서 기계적으로 채우고 누락 검사 → 모델이 축약·창작할 수 없음
  - `create_file(parentId=...)`로 처음부터 카테고리 폴더에 생성 → "생성 후 이동" 단계 삭제
  - 폴더 ID를 `config/categories.json`에 캐시, 없는 폴더는 최초 사용 시 생성
  - 중복 아카이빙 검사, 자막 확보 실패 시 중단 규칙 추가
- **v5.1.0 (Current)**: 썸네일·스틸컷 이미지 전면 제거. 클라우드 IP의 YouTube 봇 차단에 대비해
  `watch` 스킬의 Gemini 엔진을 3순위 전사 경로로 연결(20분 단위 분할, 출처 표기·검증 경고 자동 삽입).

## 절대 규칙

1. **자막 없이 내용을 쓰지 않는다.** 제목·설명·썸네일만 보고 요약이나 전문을 만들지 말 것. 자막 확보에 실패하면 아래 "자막 확보 실패 시" 절차로 가고, 사용자에게 사실대로 알린다.
2. **요약(Mode B)의 모든 주장은 `transcript.txt`에 근거한다.** 영상에 없는 내용, 외부 지식으로 보충한 내용을 화자의 말처럼 쓰지 않는다. 보충 설명이 필요하면 "(편집자 주)"로 구분한다.
3. **파일명·`<h1>`은 `[카테고리명] 영상 제목`**, 폴더명은 `N.[카테고리명]`. 이 규칙은 `build_doc.py`가 강제하므로 `content.json`의 `category`에는 번호·대괄호 없이 이름만 쓴다(예: `신학&교회`).
4. `1.[신학&교회]` 분류 영상의 채널·화자가 한국 주요 교단이 이단·사이비로 규정한 단체 소속이면(또는 불확실하면) 문서를 만들기 전에 사용자에게 알리고 진행 여부를 확인한다. 진행 시 `content.json`의 `notes`에 경고 문구를 넣는다.

## Workflow

### 0단계: 준비

```bash
pip install -q -r requirements.txt
```

**로컬 PC 실행이 기본이다.** 클라우드 세션에서는 YouTube 봇 차단 때문에 1·2순위가 거의 실패하므로, 클라우드에서 실패하면 로컬 실행을 먼저 권한다.
Windows에서는 `python3` 대신 `python`을 쓴다.

Gemini 경로를 쓰려면 `GEMINI_API_KEY`(또는 `GOOGLE_API_KEY`)가 필요하다. 클라우드 환경 설정(세션 제목 표시줄의 환경 메뉴 → Edit)의
Network secrets 또는 환경 변수에 `GEMINI_API_KEY`로 등록되어 있어야 한다. **키를 채팅으로 받지 않는다.**
키가 없으면 3순위 경로만 건너뛰고 나머지는 그대로 동작한다.

### 1단계: 모드 확정

- **Mode A (전문)**: "전문", "전체 텍스트", "대본" 요청 시 → `"mode": "A"`
- **Mode B (시각화 요약)**: "요약", "표 정리", "분석" 요청 또는 지시 없음(기본) → `"mode": "B"`
- **듀얼**: 둘 다 요청 시 → `"mode": "dual"` (요약 뒤에 전문)

### 2단계: 추출

```bash
python3 scripts/yt_fetch.py "<URL>"
```

`work/<VIDEO_ID>/`에 `meta.json`, `transcript.json`, `transcript.txt`가 생긴다. `transcript.txt`를 **끝까지** 읽는다(긴 영상은 나눠서). 종료 코드 3이면 자막 확보 실패다.

전사 확보 순서 (`--via auto`, 기본):

| 순위 | 경로 | 성격 |
| :--- | :--- | :--- |
| 1 | yt-dlp 자막 | 제작자 자막 또는 유튜브 자동 자막 원문 |
| 2 | youtube-transcript-api | 위와 동일, 다른 접근 방식 |
| 3 | `watch` 스킬 → Gemini | YouTube 차단 우회. **AI가 듣고 받아쓴 것**이라 원문 자막이 아님 |

- 이미 차단이 확인된 세션이면 `--via gemini`로 1·2순위를 건너뛰어 시간을 아낀다.
- 원문 자막만 허용하려면 `--via youtube`.
- Gemini 전사(`transcript.kind == "gemini"`)는 누락·오기·환각이 있을 수 있다. 문서에는 경고가 자동으로 들어가며,
  최종 보고에서도 사용자에게 알린다. `coverage`(전사 범위/영상 길이)가 0.9 미만이면 뒷부분 누락 가능성을 따로 알린다.
- Gemini 경로는 영상 URL을 Google에 보낸다. 공개 영상만 대상으로 하고, 비공개·일부공개 영상이면 사용자에게 먼저 묻는다.

**중복 검사**: Drive `search_files`로 `fullText contains '<VIDEO_ID>'`를 조회한다. 이미 문서가 있으면 새로 만들지 말고 사용자에게 링크를 알려 덮어쓸지 묻는다.

#### 자막 확보 실패 시

클라우드 세션의 IP는 YouTube 봇 차단("Sign in to confirm you're not a bot", HTTP 429/403)에 자주 걸린다. 스크립트가 이미 재시도했으므로:

1. 오류가 `GEMINI_API_KEY 미설정`이면 0단계대로 환경 설정에 키를 등록하도록 안내한다(새 세션부터 적용).
2. 1·2순위만 실패하고 Gemini도 일시 오류면 1~2분 뒤 한 번만 더 실행한다.
3. 그래도 실패하면 사용자에게 알리고, 유튜브 영상 설명란의 "스크립트 표시"에서 복사한 텍스트를 붙여넣어 달라고 요청한다 →
   파일로 저장 후 `python3 scripts/yt_fetch.py "<URL>" --transcript-file <파일>` (타임스탬프 줄 자동 인식)
4. 어떤 경우에도 추측으로 문서를 만들지 않는다.
5. `watch` 스킬의 로컬 엔진(yt-dlp 다운로드 + Whisper)은 같은 YouTube 차단에 걸리므로 이 환경에서는 대안이 되지 않는다.

### 3단계: 분류 및 content.json 작성

`config/categories.json`의 `scope`를 기준으로 14개 중 **하나**를 고른다. 두 곳에 걸치면 영상의 주된 논지를 따르고, 판단 근거를 최종 보고에 한 줄로 적는다.

`work/<VIDEO_ID>/content.json`을 작성한다(스키마는 `scripts/build_doc.py` 상단 주석 참조).

- **Mode B `summary`**
  - `thesis`: 핵심 명제. 합쳐서 5~7줄.
  - `logic_tree`: `level` 0(주제) / 1(➔ 논거) / 2(↳ 세부). 기호는 스크립트가 붙이므로 텍스트에 넣지 않는다.
  - `table`: 핵심 요약표. 2~4열.
  - `points`: 상세 논점. 각 논점에 해당 발언이 시작되는 `start`(초)를 넣으면 딥링크가 붙는다.
- **Mode A `sections`**: `{"start": 초, "title": "소제목", "scene": "장면 설명"}`.
  - 본문 텍스트는 쓰지 않는다. 스크립트가 `transcript.json`에서 구간별로 채운다.
  - `scene`은 자막에서 확인되는 내용만 쓴다(화면을 직접 보지 않았으므로 시각 묘사를 지어내지 않는다). 확인할 수 없으면 생략한다.
  - 생략하면 영상 챕터 → 5분 단위 순으로 자동 분할된다.

### 4단계: 문서 빌드 및 Drive 저장

```bash
python3 scripts/build_doc.py work/<VIDEO_ID>
```

출력 JSON의 `title`, `folder`, `folder_id`, `root_id`, `file_reference`를 사용한다.

1. **폴더 ID 확보**
   - `folder_id`가 있으면 그대로 쓴다.
   - `null`이면 `search_files(query="parentId = '<root_id>' and title contains '<카테고리명>'")`로 찾는다.
   - 그래도 없으면 `create_file(title="<folder>", contentMimeType="application/vnd.google-apps.folder", parentId="<root_id>")`로 만든다.
   - 찾거나 만든 ID는 `config/categories.json`에 기록하고 커밋한다.
2. **문서 생성** — Google Drive 커넥터 `create_file`:
   - `title`: 출력의 `title` 그대로
   - `contentMimeType`: `text/html` (Drive가 Google Docs로 자동 변환)
   - `parentId`: 카테고리 폴더 ID — **생성 시점에 지정하므로 별도 이동이 필요 없다**
   - 본문: `base64Content`에 출력의 `file_reference` 문자열을 그대로 넣는다(파일 내용을 직접 타이핑하지 않음). 이 방식이 거부되면 `doc.html`을 읽어 `textContent`로 전달한다.
3. **검증** — 응답의 `mimeType`이 `application/vnd.google-apps.document`이고 `parentId`가 카테고리 폴더인지 확인한다. 아니면 `update_file(fileId, parentId)`로 바로잡는다.

### 5단계: 보고

사용자에게 문서 링크, 분류와 근거, 모드, 자막 출처(제작자 등록/자동 생성/사용자 제공/Gemini 받아쓰기)를 알린다. 자동 생성 자막이면 고유명사·용어 오인식 가능성을 한 줄로 덧붙인다.

## 서식 표준 (build_doc.py가 적용 — 수정은 스크립트에서)

- 맑은 고딕 11pt, 양쪽 정렬, 줄 간격 1.15, 단락 앞·뒤 8pt. 변환 손실을 줄이려고 전부 인라인 스타일로 넣는다.
- 상단: `<h1>` 제목 → 메타데이터 표(출처·채널·분류·길이·전사 출처·적용 서식). 이미지는 넣지 않는다.
- 타임스탬프 링크는 `https://www.youtube.com/watch?v=<ID>&t=<초>s` 정식 형식.
- 장면 박스는 배경색이 있는 1칸 표로 구현한다(문단 배경·좌측 강조선은 Docs 변환에서 유실되기 쉬움).
- 썸네일·스틸컷 등 이미지는 일절 넣지 않는다.
