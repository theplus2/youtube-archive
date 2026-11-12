#!/usr/bin/env python3
"""유튜브 영상의 메타데이터와 자막(전사)을 추출해 작업 폴더에 저장한다.

사용법:
    python3 scripts/yt_fetch.py <유튜브 URL 또는 VIDEO_ID> [--out work] [--lang ko]
    python3 scripts/yt_fetch.py <URL> --transcript-file 붙여넣은자막.txt   # 수동 자막 사용

산출물 (work/<VIDEO_ID>/):
    meta.json        제목·채널·길이·챕터·자막 출처

자막 확보 순서 (--via auto):
    1) yt-dlp 자막  2) youtube-transcript-api  3) watch 스킬의 Gemini 엔진(GEMINI_API_KEY 필요)
    transcript.json  [{"start": 초, "text": "..."}]  원본 세그먼트
    transcript.txt   [HH:MM:SS] 약 20초 단위로 묶은 읽기용 텍스트

종료 코드: 0 성공 / 2 메타데이터 실패 / 3 자막 확보 실패(메타데이터는 저장됨)
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(src: str) -> str:
    if ID_RE.match(src):
        return src
    u = urllib.parse.urlparse(src)
    if u.hostname and u.hostname.endswith("youtu.be"):
        cand = u.path.strip("/").split("/")[0]
    elif u.path.startswith(("/shorts/", "/live/", "/embed/")):
        cand = u.path.split("/")[2]
    else:
        cand = urllib.parse.parse_qs(u.query).get("v", [""])[0]
    if not ID_RE.match(cand):
        sys.exit(f"VIDEO_ID를 해석할 수 없습니다: {src}")
    return cand


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def hms(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------- 메타데이터 ----------

def meta_ytdlp(vid: str):
    """(info, error). yt-dlp는 클라우드 IP에서 봇 차단에 걸릴 수 있어 재시도한다."""
    try:
        import yt_dlp
    except ImportError:
        return None, "yt-dlp 미설치 (pip install -r requirements.txt)"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "ignore_no_formats_error": True,
            "js_runtimes": {"node": {}, "deno": {}}}
    err = None
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            # 봇 차단 시 yt-dlp는 오류 대신 빈 껍데기(제목 'youtube video #ID', 자막·길이 없음)를 돌려준다.
            # 이를 성공으로 보면 "자막 트랙 없음"으로 오판하므로 실패로 처리한다.
            if not info.get("duration") or str(info.get("title", "")).startswith("youtube video #"):
                err = "봇 차단으로 불완전한 응답(제목·길이·자막 정보 없음)"
                time.sleep(2 * (attempt + 1))
                continue
            return info, None
        except Exception as e:  # noqa: BLE001
            err = str(e).splitlines()[0][:300]
            opts.pop("js_runtimes", None)  # 구버전 호환
            time.sleep(2 * (attempt + 1))
    return None, err


def meta_oembed(vid: str):
    try:
        q = urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}", safe="")
        d = json.loads(http_get(f"https://www.youtube.com/oembed?url={q}&format=json"))
        return {"title": d.get("title"), "channel": d.get("author_name")}
    except Exception:
        return None


# ---------- 자막 ----------

def parse_json3(raw: bytes):
    segs = []
    for ev in json.loads(raw).get("events", []):
        text = "".join(s.get("utf8", "") for s in ev.get("segs") or [])
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            segs.append({"start": round(ev.get("tStartMs", 0) / 1000, 2), "text": text})
    return segs


def choose_track(info: dict, want: list):
    """수동 자막 > 자동 생성 자막(원어) 순으로 고른다. 번역 트랙은 쓰지 않는다."""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    for lang in want:
        for key in manual:
            if key == lang or key.startswith(lang + "-"):
                return key, manual[key], "manual"
    for lang in want:
        for key in (f"{lang}-orig", lang):
            if key in auto:
                return key, auto[key], "auto"
    if manual:
        key = next(iter(manual))
        return key, manual[key], "manual"
    return None, None, None


def subs_ytdlp(info: dict, want: list):
    key, formats, kind = choose_track(info, want)
    if not key:
        return None, "이 영상에는 자막 트랙(수동·자동)이 없습니다"
    url = next((f["url"] for f in formats if f.get("ext") == "json3"), None)
    if not url:
        return None, f"json3 형식 자막 없음 ({key})"
    err = None
    for attempt in range(4):
        try:
            segs = parse_json3(http_get(url, 30))
            if segs:
                return {"segments": segs, "lang": key, "kind": kind, "via": "yt-dlp"}, None
            err = "자막 응답이 비어 있음"
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
        time.sleep(3 * (attempt + 1))
    return None, err


def subs_transcript_api(vid: str, want: list):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, "youtube-transcript-api 미설치"
    try:
        api = YouTubeTranscriptApi()
        tl = api.list(vid)
        try:
            tr = tl.find_manually_created_transcript(want)
        except Exception:
            tr = tl.find_generated_transcript(want)
        segs = [{"start": round(s.start, 2), "text": re.sub(r"\s+", " ", s.text).strip()}
                for s in tr.fetch() if s.text.strip()]
        return {"segments": segs, "lang": tr.language_code,
                "kind": "auto" if tr.is_generated else "manual", "via": "youtube-transcript-api"}, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e).strip().splitlines()[0][:200] if str(e).strip() else ''}"


TS_RE = re.compile(r"^\s*[-*]?\s*\[?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]?\s*[-–:]?\s*(.*)$")


def parse_timestamped(text: str):
    """줄 앞의 0:00 / 00:00:00 / [00:00:00] 타임스탬프를 인식해 세그먼트로 만든다.
    유튜브 '스크립트 표시' 복사본처럼 타임스탬프와 문장이 다른 줄에 있어도 된다."""
    segs, cur = [], None
    for line in text.splitlines():
        if not line.strip():
            continue
        m = TS_RE.match(line)
        if m:
            h, mi, s, rest = m.groups()
            cur = {"start": int(h or 0) * 3600 + int(mi) * 60 + int(s), "text": rest.strip()}
            segs.append(cur)
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + line.strip()).strip()
        else:
            cur = {"start": 0, "text": line.strip()}
            segs.append(cur)
    return [s for s in segs if s["text"]]


def subs_from_file(path: str):
    segs = parse_timestamped(Path(path).read_text(encoding="utf-8"))
    return {"segments": segs, "lang": "unknown", "kind": "user-supplied",
            "via": "file", "has_timestamps": any(s["start"] > 0 for s in segs)}


# ---------- Gemini (watch 스킬 경유) ----------
# 이 컨테이너가 YouTube에 직접 접속하지 않고, Google의 Gemini가 영상을 보고 받아쓴다.
# 따라서 YouTube의 봇 차단(403/429)을 우회하지만, 결과는 AI가 생성한 전사이므로
# 원문 자막과 달리 누락·오기·환각이 있을 수 있다(문서에 출처를 표기한다).

GEMINI_CHUNK = 1200  # 초. 출력 길이 한도 때문에 긴 영상은 20분 단위로 나눠 받아쓴다.
GEMINI_MAX_CHUNKS = 9  # 최대 3시간
GEMINI_Q = (
    "Transcribe ALL speech in this video VERBATIM in the original spoken language. "
    "Do not summarize, paraphrase, translate, correct, or omit anything. "
    "Output ONLY transcript lines in the form [HH:MM:SS] text, starting a new line at each sentence "
    "boundary and at least every 30 seconds. Timestamps must be absolute positions in the full video. "
    "Write [inaudible] for unclear parts. No headings, no visual descriptions, no commentary before or after."
)


def find_watch_script():
    env = __import__("os").environ.get("WATCH_SCRIPT")
    if env and Path(env).is_file():
        return Path(env)
    base = Path.home() / ".claude" / "plugins"
    hits = sorted(base.rglob("skills/watch/scripts/watch.py"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if base.exists() else []
    return hits[0] if hits else None


def gemini_env():
    """watch는 GEMINI_API_KEY만 읽는다. Google SDK 관례상 GOOGLE_API_KEY로 등록된 키도 넘겨준다."""
    import os
    env = dict(os.environ)
    if not env.get("GEMINI_API_KEY", "").strip() and env.get("GOOGLE_API_KEY", "").strip():
        env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]
    return env


def gemini_key_available() -> bool:
    if gemini_env().get("GEMINI_API_KEY", "").strip():
        return True
    for p in (Path.home() / ".config" / "watch" / ".env", Path.cwd() / ".env"):
        if p.exists() and re.search(r"^\s*GEMINI_API_KEY\s*=\s*\S+", p.read_text(encoding="utf-8"), re.M):
            return True
    return False


def _gemini_answer(report: str):
    if "## Answer (from Gemini)" not in report:
        errs = re.findall(r"^- (Gemini .+)$", report, re.M)
        return None, (errs[0] if errs else "Gemini 응답 없음")[:300]
    body = report.split("## Answer (from Gemini)", 1)[1]
    lines = [l for l in body.splitlines() if not (l.startswith("_") and l.rstrip().endswith("_"))]
    return "\n".join(lines).strip(), None


def subs_gemini(url: str, duration):
    import subprocess
    watch = find_watch_script()
    if not watch:
        return None, "watch 스킬(watch.py)을 찾을 수 없음"
    if not gemini_key_available():
        return None, "GEMINI_API_KEY 미설정 (SKILL.md '0단계' 참조)"
    segs, start = [], 0
    for _ in range(GEMINI_MAX_CHUNKS):
        if duration and start >= duration:
            break
        end = start + GEMINI_CHUNK
        q = GEMINI_Q
        cmd = [sys.executable, str(watch), url, "--engine", "gemini"]
        if not (duration and duration <= GEMINI_CHUNK):
            cmd += ["--start", hms(start), "--end", hms(end)]
            q += f" This excerpt covers {hms(start)}–{hms(end)} of the full video."
        print(f"[gemini] {hms(start)}~ 받아쓰는 중…", file=sys.stderr)
        text, err = None, None
        for attempt in range(4):  # 503 과부하·연결 끊김은 일시적이므로 간격을 늘려 재시도
            try:
                r = subprocess.run(cmd + ["--question", q], capture_output=True, text=True, timeout=1200,
                                   env=gemini_env())
            except subprocess.TimeoutExpired:
                return None, f"Gemini 시간 초과 ({hms(start)} 구간)"
            text, err = _gemini_answer(r.stdout)
            if text or not err or not re.search(r"Gemini (service|network)", err):
                break
            wait = 30 * (attempt + 1)
            print(f"[gemini] 일시 오류, {wait}초 후 재시도: {err[:120]}", file=sys.stderr)
            time.sleep(wait)
        chunk = parse_timestamped(text) if text else []
        if not chunk:
            if start > 0 and segs:  # 영상 끝을 지난 구간 → 정상 종료
                break
            return None, f"Gemini: {err or '타임스탬프 형식의 전사를 받지 못함'}"
        # 구간 상대 시각으로 답했으면 절대 시각으로 보정
        if start > 0 and chunk[0]["start"] < start - 60:
            for s in chunk:
                s["start"] += start
        last = segs[-1]["start"] if segs else -1
        segs += [s for s in chunk if s["start"] > last]
        if duration and duration <= GEMINI_CHUNK:
            break
        # 길이를 모르면 빈 구간(또는 오류)이 나올 때까지 계속한다. 중간의 긴 침묵을 영상 끝으로
        # 오판해 뒷부분을 잃는 것보다 호출 1회를 더 쓰는 편이 낫다.
        start = end
    coverage = None
    if duration and segs:
        coverage = round(min(segs[-1]["start"] / duration, 1.0), 2)
    return {"segments": segs, "lang": "unknown", "kind": "gemini", "via": "watch/gemini",
            "coverage": coverage}, None


def write_txt(segs, path: Path, window: int = 20):
    lines, buf, t0 = [], [], None
    for s in segs:
        if t0 is None:
            t0 = s["start"]
        if s["start"] - t0 >= window and buf:
            lines.append(f"[{hms(t0)}] {' '.join(buf)}")
            buf, t0 = [], s["start"]
        buf.append(s["text"])
    if buf:
        lines.append(f"[{hms(t0)}] {' '.join(buf)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", default="work")
    ap.add_argument("--lang", default=None, help="우선 자막 언어 (기본: 영상 원어 → ko → en)")
    ap.add_argument("--transcript-file", default=None, help="직접 확보한 자막 텍스트 파일")
    ap.add_argument("--via", choices=("auto", "youtube", "gemini"), default="auto",
                    help="auto: YouTube 자막 → 실패 시 Gemini / youtube: 자막만 / gemini: 바로 Gemini")
    a = ap.parse_args()

    vid = video_id(a.source)
    out = Path(a.out) / vid
    out.mkdir(parents=True, exist_ok=True)

    info, meta_err = meta_ytdlp(vid) if a.via != "gemini" else (None, "yt-dlp 생략 (--via gemini)")
    meta = {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}
    if info:
        meta.update({
            "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "channel_url": info.get("channel_url"), "duration": info.get("duration"),
            "upload_date": info.get("upload_date"), "language": info.get("language"),
            "description": (info.get("description") or "")[:3000],
            "chapters": [{"start": int(c["start_time"]), "title": c["title"]} for c in info.get("chapters") or []],
            "meta_via": "yt-dlp",
        })
    else:
        o = meta_oembed(vid)
        if not o:
            print(f"[실패] 메타데이터를 가져오지 못했습니다: {meta_err}", file=sys.stderr)
            sys.exit(2)
        meta.update(o)
        meta.update({"duration": None, "chapters": [], "meta_via": "oembed", "meta_warning": meta_err})

    want = [x for x in dict.fromkeys([a.lang, (info or {}).get("language"), "ko", "en"]) if x]
    tr, errors = None, []
    if a.transcript_file:
        tr = subs_from_file(a.transcript_file)
    else:
        if a.via != "gemini":
            if info:
                tr, e = subs_ytdlp(info, want)
                if e:
                    errors.append(f"yt-dlp: {e}")
            if not tr:
                tr, e = subs_transcript_api(vid, want)
                if e:
                    errors.append(f"youtube-transcript-api: {e}")
        if not tr and a.via != "youtube":
            tr, e = subs_gemini(meta["url"], meta.get("duration"))
            if e:
                errors.append(f"gemini: {e}")

    if tr:
        segs = tr.pop("segments")
        meta["transcript"] = {**tr, "segments": len(segs), "chars": sum(len(s["text"]) for s in segs)}
        (out / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
        write_txt(segs, out / "transcript.txt")
    else:
        meta["transcript"] = None
        meta["transcript_errors"] = errors
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: meta.get(k) for k in
                      ("video_id", "title", "channel", "duration", "transcript", "meta_via")},
                     ensure_ascii=False, indent=2))
    print(f"작업 폴더: {out}")
    if not tr:
        print("\n[자막 확보 실패] " + " / ".join(errors), file=sys.stderr)
        print("→ 내용을 추측해 문서를 만들지 말 것. SKILL.md의 '자막 확보 실패 시' 절차를 따를 것.", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
