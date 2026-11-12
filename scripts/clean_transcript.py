#!/usr/bin/env python3
"""전문(Mode A) 교정 단계: 자막 원문을 청크로 나누고, Claude가 쓴 교정본을 검사한다.

사용법:
    python3 scripts/clean_transcript.py prep  work/<VIDEO_ID>   # 원문 청크 생성
    python3 scripts/clean_transcript.py check work/<VIDEO_ID>   # 교정본 검사(누락·축약 탐지)

prep 결과 (work/<ID>/clean/):
    01.raw.txt, 02.raw.txt, ...   [HH:MM:SS] 원문 줄 (약 20초 단위)
    manifest.json                 청크별 시작·끝 시각과 원문 글자 수

Claude가 쓰는 교정본: 같은 폴더의 01.txt, 02.txt, ...
    - 문단마다 맨 앞에 [HH:MM:SS] 태그 (원문 줄의 태그 중 그 문단이 시작되는 줄의 것을 그대로 복사)
    - 문단 사이는 빈 줄 한 줄. 화자가 바뀌면(원문의 >>) 새 문단.
    - 요약·생략·의역 금지. 오인식·맞춤법·띄어쓰기·문장부호만 바로잡는다.

check는 다음을 검사하고, 하나라도 어기면 종료 코드 1로 끝난다(build_doc.py도 같은 검사를 한다).
    - 모든 청크에 교정본이 있는지
    - 교정본 글자 수가 원문의 MIN_RATIO~MAX_RATIO 범위인지 (요약·창작 방지)
    - 태그 형식과 시간 순서, 각 태그가 해당 청크 시간 범위 안인지
"""
import difflib
import json
import re
import sys
from pathlib import Path

CHUNK_CHARS = 2200          # 청크당 원문 글자 수 목표
LINE_SECS = 20              # 원문 한 줄로 묶는 시간 폭
LINE_CHARS = 400            # 타임스탬프가 없을 때도 줄이 무한정 길어지지 않게
MIN_RATIO, MAX_RATIO = 0.75, 1.30
WARN_RATIO = 0.97
MIN_COVERAGE = 0.88         # 원문 글자(한글·숫자·영문) 중 교정본에 그대로 남아야 하는 비율
MAX_GAP = 20                # 교정본에 대응하는 곳이 없는 원문 연속 구간 최대 길이(글자)
TAG = re.compile(r"^\[(\d{1,2}):([0-5]\d):([0-5]\d)\]\s*")
CORE = re.compile(r"[^가-힣0-9A-Za-z]")
SENTENCE_END = (".", "?", "!", "…", '"', "”", "'", "’", "]", ")", "」", "』")
TAG_ANY = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]")
NOISE = re.compile(r">>|\s|\[(?:\d{1,2}:)?\d{2}:\d{2}\]")


def hms(sec) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def die(msg: str):
    print(f"[오류] {msg}", file=sys.stderr)
    sys.exit(1)


def size(text: str) -> int:
    """비교용 글자 수: 공백·>>·타임스탬프 제외."""
    return len(NOISE.sub("", text))


def coverage(raw: str, corr: str):
    """원문 글자가 교정본에 얼마나 남았는지와, 대응이 없는 가장 긴 원문 구간을 돌려준다."""
    a = CORE.sub("", TAG_ANY.sub("", raw))
    b = CORE.sub("", TAG_ANY.sub("", corr))
    if not a:
        return 1.0, ""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched, pos, gap = 0, 0, ""
    for blk in sm.get_matching_blocks():
        if blk.a - pos > len(gap):
            gap = a[pos:blk.a]
        matched += blk.size
        pos = blk.a + blk.size
    return matched / len(a), gap


def lines_of(segs):
    """세그먼트를 약 LINE_SECS초(타임스탬프가 없으면 LINE_CHARS자) 단위 줄로 묶는다."""
    out, buf, t0 = [], [], None
    for s in segs:
        if t0 is None:
            t0 = s["start"]
        if buf and (s["start"] - t0 >= LINE_SECS or sum(len(x) for x in buf) >= LINE_CHARS):
            out.append((t0, " ".join(buf)))
            buf, t0 = [], s["start"]
        buf.append(s["text"].strip())
    if buf:
        out.append((t0, " ".join(buf)))
    return out


def prep(work: Path):
    tp = work / "transcript.json"
    if not tp.exists():
        die(f"{tp} 가 없습니다. 먼저 yt_fetch.py를 실행할 것.")
    segs = json.loads(tp.read_text(encoding="utf-8"))
    lines = lines_of(segs)
    chunks, cur = [], []
    for ln in lines:
        cur.append(ln)
        if sum(len(t) for _, t in cur) >= CHUNK_CHARS:
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and sum(len(t) for _, t in cur) < CHUNK_CHARS * 0.35:
            chunks[-1] += cur          # 너무 짧은 꼬리는 앞 청크에 붙인다
        else:
            chunks.append(cur)

    d = work / "clean"
    d.mkdir(exist_ok=True)
    for old in d.glob("*.raw.txt"):
        old.unlink()
    stale = sorted(d.glob("[0-9][0-9].txt"))
    if stale:                          # 이전 교정본은 지우지 않고 옮겨 둔다
        (d / "old").mkdir(exist_ok=True)
        for f in stale:
            f.replace(d / "old" / f.name)
        print(f"[주의] 이전 교정본 {len(stale)}개를 clean/old/ 로 옮겼습니다", file=sys.stderr)
    manifest = []
    for i, ch in enumerate(chunks, 1):
        name = f"{i:02d}"
        body = "\n".join(f"[{hms(t)}] {txt}" for t, txt in ch) + "\n"
        (d / f"{name}.raw.txt").write_bytes(body.encode("utf-8"))
        end = chunks[i][0][0] if i < len(chunks) else segs[-1]["start"] + 30
        manifest.append({"id": name, "start": ch[0][0], "end": end, "raw_chars": size(body)})
    (d / "manifest.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
    print(json.dumps({"chunks": len(manifest), "dir": str(d.resolve()),
                      "files": [f"{m['id']}.raw.txt" for m in manifest]}, ensure_ascii=False, indent=2))


def load(work: Path, strict: bool = True):
    """교정본을 읽어 [(start초, 문단)] 목록과 경고 목록을 돌려준다. 규칙 위반이면 die.

    문단 이어 붙이기: 청크의 마지막 문단이 문장 중간에서 끝나면(청크 경계에서 잘린 문장) 다음 청크의 첫 문단을 잇는다.
    청크 안에서 문장 중간에 끝난 문단은 잇지 않고 경고만 한다(끊긴 말은 교정본에서 '…'로 끝내야 한다).
    """
    d = work / "clean"
    mp = d / "manifest.json"
    if not mp.exists():
        die(f"{mp} 가 없습니다. 먼저 'clean_transcript.py prep {work}' 를 실행할 것.")
    manifest = json.loads(mp.read_text(encoding="utf-8-sig"))
    if not manifest:
        die("manifest.json 에 청크가 없습니다(자막이 비어 있음).")
    paras, warns, errs = [], [], []
    last = -1.0
    carry = False
    for m in manifest:
        f = d / f"{m['id']}.txt"
        if not f.exists():
            errs.append(f"{f.name} 없음 (원문 {m['id']}.raw.txt 의 교정본)")
            carry = False
            continue
        text = f.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
        raw = (d / f"{m['id']}.raw.txt").read_text(encoding="utf-8-sig")
        ratio = size(text) / max(m["raw_chars"], 1)
        cov, gap = coverage(raw, text)
        if not MIN_RATIO <= ratio <= MAX_RATIO:
            errs.append(f"{f.name}: 글자 수 비율 {ratio:.2f} (허용 {MIN_RATIO}~{MAX_RATIO}). 요약·생략 또는 창작 의심")
        elif ratio < WARN_RATIO:
            warns.append(f"{f.name}: 글자 수 비율 {ratio:.2f} — 빠진 내용이 없는지 다시 볼 것")
        if cov < MIN_COVERAGE:
            errs.append(f"{f.name}: 원문 보존율 {cov:.2f} (최소 {MIN_COVERAGE}). 원문이 많이 바뀌거나 빠졌다")
        if len(gap) >= MAX_GAP:
            errs.append(f"{f.name}: 교정본에 없는 원문 구간 {len(gap)}자 — '{gap[:40]}…' (빠진 문장인지 확인)")
        blocks = [" ".join(x.strip() for x in b.splitlines() if x.strip()) for b in re.split(r"\n\s*\n", text)]
        blocks = [b for b in blocks if b]
        for k, block in enumerate(blocks):
            mt = TAG.match(block)
            if not mt:
                errs.append(f"{f.name}: 태그 없는 문단 — '{block[:30]}…'")
                continue
            t = int(mt[1]) * 3600 + int(mt[2]) * 60 + int(mt[3])
            if not (int(m["start"]) <= t <= int(m["end"]) + 1):
                errs.append(f"{f.name}: [{hms(t)}] 가 청크 범위 {hms(m['start'])}~{hms(m['end'])} 밖")
            if t < last:
                errs.append(f"{f.name}: [{hms(t)}] 가 앞 문단보다 이르다(시간 역순)")
            last = max(last, t)
            body = block[mt.end():].strip()
            if not body:
                continue
            if carry and k == 0 and paras:
                paras[-1] = (paras[-1][0], paras[-1][1] + " " + body)
            else:
                paras.append((t, body))
            open_end = not body.endswith(SENTENCE_END)
            if open_end and k < len(blocks) - 1:
                warns.append(f"{f.name}: [{hms(t)}] 문단이 문장 중간에서 끝남 — 끊긴 말이면 '…'로 끝내고, 아니면 다음 문단과 합칠 것")
        carry = bool(blocks) and not blocks[-1].endswith(SENTENCE_END)
    if errs and strict:
        die("교정본 검사 실패:\n  - " + "\n  - ".join(errs))
    return paras, warns + errs


def check(work: Path):
    paras, warns = load(work)
    for w in warns:
        print(f"[주의] {w}", file=sys.stderr)
    print(json.dumps({"ok": True, "paragraphs": len(paras), "warnings": len(warns)}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("prep", "check"):
        die("사용법: python3 scripts/clean_transcript.py prep|check work/<VIDEO_ID>")
    {"prep": prep, "check": check}[sys.argv[1]](Path(sys.argv[2]))
