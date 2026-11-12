#!/usr/bin/env python3
"""content.json + meta.json + transcript.json → 구글 문서 변환용 HTML(doc.html)을 만든다.

사용법:
    python3 scripts/build_doc.py work/<VIDEO_ID>

서식(글꼴·정렬·줄간격·딥링크·파일명 규칙)은 전부 이 스크립트가 고정한다.
Claude는 content.json에 '내용'만 쓴다. 전문(Mode A)의 본문은 transcript.json에서
기계적으로 채우므로 모델이 축약하거나 지어낼 수 없다.

content.json 스키마:
{
  "category": "신학&교회",            # config/categories.json의 name (번호·대괄호 없이)
  "mode": "B",                        # "A" 전문 | "B" 시각화 요약 | "dual" 둘 다
  "summary": {                        # mode B / dual
    "thesis": ["문단", ...],          # 핵심 명제 (합쳐서 5~7줄)
    "logic_tree": [{"level": 0, "text": "..."}, {"level": 1, "text": "..."}],
    "table": {"headers": ["구분", "내용"], "rows": [["...", "..."]]},
    "points": [{"title": "논점", "start": 400, "items": ["...", "..."]}]   # start(초)는 선택
  },
  "sections": [                       # mode A / dual. 생략하면 챕터 → 5분 단위로 자동 분할
    {"start": 0, "title": "소제목", "scene": "장면 설명(선택)"}
  ],
  "notes": ["문서 상단에 표시할 주의 문구(선택)"]
}
"""
import hashlib
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = "font-family:'Malgun Gothic','맑은 고딕',sans-serif;"
P = f"{FONT}font-size:11pt;text-align:justify;line-height:1.15;margin-top:8pt;margin-bottom:8pt;"
H1 = f"{FONT}font-size:20pt;font-weight:bold;line-height:1.15;margin-top:0;margin-bottom:10pt;"
H2 = f"{FONT}font-size:15pt;font-weight:bold;line-height:1.15;margin-top:18pt;margin-bottom:6pt;"
H3 = f"{FONT}font-size:12.5pt;font-weight:bold;line-height:1.15;margin-top:12pt;margin-bottom:4pt;"
CELL = f"{FONT}font-size:10.5pt;line-height:1.15;padding:5pt 7pt;border:1px solid #9aa0a6;vertical-align:top;"
TH = CELL + "background-color:#e8eef7;font-weight:bold;text-align:center;"
BOX = f"{FONT}font-size:10pt;line-height:1.15;padding:6pt 9pt;background-color:#f3f6fb;border:1px solid #c9d3e3;"
TABLE = "border-collapse:collapse;width:100%;"

e = html.escape


def hms(sec) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def p(text: str, style: str = P) -> str:
    return f'<p align="justify" style="{style}">{text}</p>'


def die(msg: str):
    print(f"[오류] {msg}", file=sys.stderr)
    sys.exit(1)


def paragraphs(segs, max_chars: int = 600, max_secs: int = 75):
    """세그먼트를 읽기 좋은 문단으로 묶는다. 텍스트 자체는 바꾸지 않는다."""
    out, buf, t0 = [], [], None
    for s in segs:
        if t0 is None:
            t0 = s["start"]
        buf.append(s["text"])
        size = sum(len(x) for x in buf)
        ends = s["text"].rstrip().endswith((".", "?", "!", "다", "요", "죠", "…"))
        if size >= max_chars * 1.6 or ((size >= max_chars or s["start"] - t0 >= max_secs) and ends):
            out.append((t0, " ".join(buf)))
            buf, t0 = [], None
    if buf:
        out.append((t0, " ".join(buf)))
    return out


def main():
    if len(sys.argv) != 2:
        die("사용법: python3 scripts/build_doc.py work/<VIDEO_ID>")
    work = Path(sys.argv[1])
    for f in ("meta.json", "content.json"):
        if not (work / f).exists():
            die(f"{work / f} 가 없습니다")
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    content = json.loads((work / "content.json").read_text(encoding="utf-8"))
    cats = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))

    cat = next((c for c in cats["categories"] if c["name"] == content.get("category")), None)
    if not cat:
        die(f"category '{content.get('category')}' 는 14대 카테고리에 없습니다 (번호·대괄호 없이 name만 쓸 것): "
            + ", ".join(c["name"] for c in cats["categories"]))
    mode = content.get("mode", "B")
    if mode not in ("A", "B", "dual"):
        die("mode는 A, B, dual 중 하나")

    vid = meta["video_id"]
    watch = f"https://www.youtube.com/watch?v={vid}"
    title = f"[{cat['name']}] {meta['title']}".strip()

    def link(sec, label):
        return f'<a href="{watch}&t={int(sec)}s">{e(label)}</a>'

    segs = []
    if mode in ("A", "dual"):
        tp = work / "transcript.json"
        if not tp.exists():
            die("전문(Mode A)에는 transcript.json이 필요합니다. 자막 없이 전문을 만들 수 없습니다.")
        segs = json.loads(tp.read_text(encoding="utf-8"))
    tr = meta.get("transcript") or {}
    has_ts = tr.get("has_timestamps", True)

    kind = {"manual": "제작자 등록 자막", "auto": "유튜브 자동 생성 자막(오인식 가능)",
            "user-supplied": "사용자 제공 전사",
            "gemini": "Gemini AI 받아쓰기(원문 자막 아님 · 검증 필요)"}.get(tr.get("kind"), "없음")
    mode_label = {"A": "Mode A · 전문 텍스트", "B": "Mode B · 시각화 요약", "dual": "듀얼 통합 (요약 + 전문)"}[mode]
    rows = [
        ("영상 출처", f'<a href="{watch}">{watch}</a>'),
        ("채널명", e(meta.get("channel") or "-")),
        ("분류", e(cat["folder"])),
        ("영상 길이", hms(meta["duration"]) if meta.get("duration") else "-"),
        ("전사 출처", e(f"{kind} · {tr.get('lang', '-')}") if tr else "없음"),
        ("적용 서식", e(f"{mode_label} / 맑은 고딕 11pt · 양쪽 정렬 · 줄 간격 1.15")),
    ]

    b = [f'<h1 style="{H1}">{e(title)}</h1>',
         f'<table border="1" style="{TABLE}">'
         + "".join(f'<tr><td style="{TH}width:22%;">{k}</td><td style="{CELL}">{v}</td></tr>' for k, v in rows)
         + "</table>"]
    for n in content.get("notes") or []:
        b.append(p(f"<b>⚠️ {e(n)}</b>"))

    # ---------- Mode B ----------
    if mode in ("B", "dual"):
        s = content.get("summary") or {}
        if not s.get("thesis"):
            die("mode B/dual에는 summary.thesis가 필요합니다")
        b.append(f'<h2 style="{H2}">1. 핵심 명제</h2>')
        b += [p(e(t)) for t in s["thesis"]]
        if s.get("logic_tree"):
            b.append(f'<h2 style="{H2}">2. 핵심 로직 트리</h2>')
            for n in s["logic_tree"]:
                lv = int(n.get("level", 0))
                mark = "" if lv == 0 else ("➔ " if lv == 1 else "↳ ")
                txt = f"<b>{e(n['text'])}</b>" if lv == 0 else e(n["text"])
                b.append(f'<p style="{P}text-align:left;margin-top:3pt;margin-bottom:3pt;margin-left:{lv * 22}pt;">{mark}{txt}</p>')
        t = s.get("table")
        if t:
            b.append(f'<h2 style="{H2}">3. 핵심 요약표</h2>')
            b.append(f'<table border="1" style="{TABLE}"><tr>'
                     + "".join(f'<th style="{TH}">{e(h)}</th>' for h in t["headers"]) + "</tr>"
                     + "".join("<tr>" + "".join(f'<td style="{CELL}">{e(str(c))}</td>' for c in r) + "</tr>"
                               for r in t["rows"]) + "</table>")
        if s.get("points"):
            b.append(f'<h2 style="{H2}">4. 상세 논점</h2>')
            for pt in s["points"]:
                head = e(pt["title"])
                if pt.get("start") is not None and has_ts:
                    head += " " + link(pt["start"], f"[{hms(pt['start'])}] ▶")
                b.append(f'<h3 style="{H3}">{head}</h3>')
                b.append("<ul>" + "".join(f'<li style="{P}margin-top:3pt;margin-bottom:3pt;">{e(i)}</li>'
                                          for i in pt["items"]) + "</ul>")

    # ---------- Mode A ----------
    if mode in ("A", "dual"):
        b.append(f'<h2 style="{H2}">{"5. " if mode == "dual" else ""}전문 텍스트</h2>')
        if tr.get("kind") == "auto":
            b.append(p("※ 유튜브 자동 생성 자막을 그대로 옮긴 것입니다. 고유명사·전문용어 오인식이 있을 수 있으니 인용 전 원본 영상을 확인하십시오.",
                       P + "color:#5f6368;font-size:10pt;"))
        if tr.get("kind") == "gemini":
            cov = tr.get("coverage")
            cov_txt = f" 영상 길이 대비 전사 범위 약 {int(cov * 100)}%." if cov is not None else ""
            b.append(p("※ 원문 자막이 아니라 Gemini AI가 영상을 듣고 받아쓴 텍스트입니다. 누락·오기·없는 말이 섞일 수 있으니 "
                       "인용 전 반드시 해당 타임스탬프의 원본 영상을 확인하십시오." + cov_txt,
                       P + "color:#b3261e;font-size:10pt;"))
        secs =content.get("sections") or [{"start": c["start"], "title": c["title"]} for c in meta.get("chapters") or []]
        if not secs:
            end = segs[-1]["start"] if segs else 0
            secs = [{"start": t, "title": f"구간 {i + 1}"} for i, t in enumerate(range(0, int(end) + 1, 300))]
        secs = sorted(secs, key=lambda x: x["start"])
        if secs[0]["start"] > (segs[0]["start"] if segs else 0):
            secs.insert(0, {"start": 0, "title": "도입"})
        used = 0
        for i, sec in enumerate(secs):
            nxt = secs[i + 1]["start"] if i + 1 < len(secs) else float("inf")
            chunk = [s for s in segs if sec["start"] <= s["start"] < nxt]
            used += len(chunk)
            stamp = hms(sec["start"])
            if has_ts:
                b.append(f'<h2 style="{H2}">' + link(sec["start"], f"[{stamp}] {sec['title']} (▶ 해당 장면 재생)") + "</h2>")
                scene = link(sec["start"], f"{stamp} 영상 프레임 바로가기")
                if sec.get("scene"):
                    scene += " — " + e(sec["scene"])
                b.append(f'<table style="{TABLE}"><tr><td style="{BOX}">🎬 {scene}</td></tr></table>')
            else:
                b.append(f'<h2 style="{H2}">{e(sec["title"])}</h2>')
            b += [p(e(text)) for _, text in paragraphs(chunk)]
        if used != len(segs):
            die(f"전문 누락: 세그먼트 {len(segs)}개 중 {used}개만 배치됨. sections의 start 값을 확인할 것.")

    doc = ('<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
           f"<title>{e(title)}</title></head><body style=\"{FONT}font-size:11pt;\">" + "\n".join(b) + "</body></html>")
    out = work / "doc.html"
    data = doc.encode("utf-8")
    out.write_bytes(data)  # write_text는 Windows에서 줄바꿈을 CRLF로 바꿔 해시가 어긋난다
    digest = hashlib.sha256(data).hexdigest()
    print(json.dumps({
        "title": title,
        "folder": cat["folder"],
        "folder_id": cat["folder_id"],
        "root_id": cats["root"]["id"],
        "html_path": str(out.resolve()),
        "html_bytes": len(data),
        "file_reference": f"sha256:{digest}:{out.resolve()}",
        "transcript_segments_placed": len(segs) if mode != "B" else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
