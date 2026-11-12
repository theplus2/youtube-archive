# youtube-archive

유튜브 영상의 자막을 추출해 14대 카테고리로 분류하고, 서식이 적용된 구글 문서로
Google Drive `YouTube지식 통합아카이빙` 폴더에 저장하는 Claude Code 스킬 저장소.

## 사용법

이 저장소를 연 Claude Code 세션에서 유튜브 URL과 함께 요청한다.

```
https://www.youtube.com/watch?v=... 요약해서 아카이빙해줘        ← Mode B (기본)
https://youtu.be/... 전문 텍스트로 정리해줘                     ← Mode A
https://youtu.be/... 전문과 시각화 자료 둘 다                   ← 듀얼
```

필요 조건: Google Drive 커넥터 연결, 환경의 네트워크 정책이 `youtube.com` · `img.youtube.com` · `pypi.org` 허용.

## 구조

| 경로 | 역할 |
| :--- | :--- |
| `.claude/skills/youtube-archive/SKILL.md` | 워크플로와 규칙 (Claude가 읽는 지침) |
| `scripts/yt_fetch.py` | 메타데이터·자막 추출 → `work/<ID>/` |
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

## 알려진 한계

- **자막 추출은 클라우드 IP에서 불안정하다.** YouTube가 봇 차단(403/429, "Sign in to confirm")을 걸면
  재시도 후에도 실패할 수 있다. 이때는 유튜브의 "스크립트 표시" 텍스트를 붙여넣어
  `--transcript-file`로 넘긴다.
- 자막 트랙이 없는 영상은 전사(Whisper 등)가 별도로 필요하다.
- 자동 생성 자막은 고유명사·전문용어 오인식이 있다. 문서 상단에 전사 출처가 표기된다.
- `hq1~3.jpg` 스틸컷은 유튜브 자동 생성 이미지로, 특정 타임스탬프의 프레임이 아니다.
- HTML → Google Docs 변환은 Drive가 수행하며 일부 CSS는 유실될 수 있다.
