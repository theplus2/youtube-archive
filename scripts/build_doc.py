#!/usr/bin/env python3
"""content.json + meta.json + transcript(교정본) → 구글 문서 변환용 HTML(doc.html)을 만든다.

사용법:
    python3 scripts/build_doc.py work/<VIDEO_ID>

서식(글꼴·색·여백·딥링크·파일명 규칙)은 전부 이 스크립트가 고정한다.
Claude는 content.json에 '내용'만 쓴다.

전문(Mode A) 본문:
  - 기본: work/<ID>/clean/ 의 Claude 교정본(clean_transcript.py 참고)을 쓴다. 누락·축약 검사를 통과해야 한다.
  - content.json에 "cleanup": false 이면 자막 원문을 그대로 쓴다(화자 전환 >> 기준으로 문단 분리).

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
    {"start": 0, "anchor": "그 문단의 첫 말(선택)", "title": "소제목"}
  ],
  "cleanup": true,                    # mode A / dual. false면 교정 없이 원문
  "corrections": [["자막 원문", "교정"], ...],   # 선택. 문서 끝 '주요 교정 어휘' 표
  "notes": ["문서 상단 '읽기 전에' 상자에 넣을 문구(선택)"]
}
"""
import datetime
import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_transcript  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERSION = "5.2.0"

# ---------- 디자인 토큰 (Google Docs HTML 가져오기에서 살아남는 속성만 사용) ----------
INK, MUTED, FAINT = "#202124", "#5f6368", "#9aa0a6"
ACCENT, ACCENT_BG = "#1f4e8c", "#eef3fa"
LINE = "#dadce0"
NOTE_BG, NOTE_LINE = "#fff8e1", "#f0d58c"
FONT = "font-family:'Noto Sans KR',sans-serif;"
BASE = f"{FONT}color:{INK};"

P = f"{BASE}font-size:11pt;line-height:1.7;text-align:left;margin-top:0;margin-bottom:10pt;"
SMALL = f"{FONT}color:{MUTED};font-size:9.5pt;line-height:1.5;margin-top:0;margin-bottom:4pt;"
KICKER = f"{FONT}color:{ACCENT};font-size:10pt;font-weight:bold;line-height:1.4;margin-top:0;margin-bottom:4pt;"
H1 = f"{BASE}font-size:19pt;font-weight:bold;line-height:1.35;margin-top:0;margin-bottom:14pt;"
H2 = f"{FONT}color:{ACCENT};font-size:15pt;font-weight:bold;line-height:1.4;margin-top:26pt;margin-bottom:4pt;"
H3 = f"{BASE}font-size:12.5pt;font-weight:bold;line-height:1.4;margin-top:18pt;margin-bottom:4pt;"
TABLE = "border-collapse:collapse;width:100%;"
CELL = f"{BASE}font-size:10pt;line-height:1.5;padding:5pt 8pt;border:1px solid {LINE};vertical-align:top;text-align:left;"
LABEL = CELL + f"background-color:{ACCENT_BG};color:{MUTED};font-weight:bold;width:20%;"
TH = CELL + f"background-color:{ACCENT};color:#ffffff;font-weight:bold;"
NOTE = f"{BASE}font-size:10pt;line-height:1.6;padding:8pt 11pt;background-color:{NOTE_BG};border:1px solid {NOTE_LINE};"
CALLOUT = f"{BASE}font-size:11pt;line-height:1.7;padding:10pt 12pt;background-color:{ACCENT_BG};border:1px solid #c9d7ec;"
TOC_CELL = f"{BASE}font-size:10pt;line-height:1.2;padding:2pt 6pt;border:1px solid #ffffff;border-bottom:1px solid #eceef1;vertical-align:top;text-align:left;"
TOC_TIME = TOC_CELL + f"width:12%;color:{MUTED};"
TOC_TITLE = TOC_CELL

e = html.escape


def hms(sec) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def short(sec, long_video: bool) -> str:
    s = int(sec)
    return hms(s) if long_video else f"{s // 60:02d}:{s % 60:02d}"


def duration_ko(sec) -> str:
    s = int(sec)
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return (f"{h}시간 " if h else "") + f"{m}분 {x}초"


def p(text: str, style: str = P) -> str:
    return f'<p style="{style}">{text}</p>'


def box(inner: str, style: str) -> str:
    """배경색 상자. 문단 배경은 Docs 변환에서 유실되므로 1칸 표로 만든다."""
    return f'<table style="{TABLE}"><tr><td style="{style}">{inner}</td></tr></table>'


def die(msg: str):
    print(f"[오류] {msg}", file=sys.stderr)
    sys.exit(1)


def entities(s: str) -> str:
    """BMP 밖 문자(이모지 등)를 숫자 참조로 바꾼다. Drive 변환에서 깨지는 것을 막는다."""
    return "".join(c if ord(c) < 0x10000 else f"&#x{ord(c):X};" for c in s)


def raw_paragraphs(segs, max_chars: int = 500):
    """교정 없이 원문을 쓸 때: 화자 전환(>>)과 길이 기준으로 문단을 나눈다. 텍스트는 바꾸지 않는다."""
    out, buf, t0 = [], [], None

    def flush():
        nonlocal buf, t0
        txt = " ".join(x for x in buf if x).strip()
        if txt:
            out.append((t0, txt))
        buf, t0 = [], None

    for s in segs:
        parts = s["text"].split(">>")
        for k, part in enumerate(parts):
            if k > 0:
                flush()
            if t0 is None:
                t0 = s["start"]
            buf.append(part.strip())
        size = sum(len(x) for x in buf)
        if size >= max_chars * 1.6 or (size >= max_chars and s["text"].rstrip().endswith((".", "?", "!", "다", "요", "죠"))):
            flush()
    flush()
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

    def link(sec, label, color=ACCENT, size=None):
        st = f"color:{color};text-decoration:none;" + (f"font-size:{size};" if size else "")
        return f'<a href="{watch}&amp;t={int(sec)}s"><span style="{st}">{e(label)}</span></a>'

    tr = meta.get("transcript") or {}
    has_ts = tr.get("has_timestamps", True)

    # ---------- 전문 문단 확보 ----------
    paras, cleaned, clean_warns = [], False, []
    if mode in ("A", "dual"):
        tp = work / "transcript.json"
        if not tp.exists():
            die("전문(Mode A)에는 transcript.json이 필요합니다. 자막 없이 전문을 만들 수 없습니다.")
        segs = json.loads(tp.read_text(encoding="utf-8"))
        if content.get("cleanup", True):
            paras, clean_warns = clean_transcript.load(work)
            cleaned = True
        else:
            paras = raw_paragraphs(segs)
        if not paras:
            die("전문 문단이 비어 있습니다.")
    long_video = max(meta.get("duration") or 0, paras[-1][0] if paras else 0) >= 3600

    kind = {"manual": "제작자 등록 자막", "auto": "유튜브 자동 생성 자막",
            "user-supplied": "사용자 제공 전사",
            "gemini": "Gemini AI 받아쓰기(원문 자막 아님)"}.get(tr.get("kind"), "없음")
    if cleaned:
        kind += " → Claude 교정"
    mode_label = {"A": "전문 텍스트", "B": "시각화 요약", "dual": "요약 + 전문"}[mode]
    up = meta.get("upload_date") or ""
    up = f"{up[:4]}.{up[4:6]}.{up[6:]}" if len(up) == 8 else "-"

    # ---------- 머리말 ----------
    b = [p(e(f"YouTube 지식 아카이브  ·  {mode_label}"), KICKER),
         f'<h1 style="{H1}">{e(title)}</h1>']
    rows = [
        ("영상", f'<a href="{watch}"><span style="color:{ACCENT};">{e(watch)}</span></a>'),
        ("채널", e(meta.get("channel") or "-")),
        ("게시일 · 길이", e(f"{up}  ·  {duration_ko(meta['duration'])}" if meta.get("duration") else up)),
        ("전사 출처", e(kind)),
    ]
    b.append(f'<table style="{TABLE}">'
             + "".join(f'<tr><td style="{LABEL}">{k}</td><td style="{CELL}">{v}</td></tr>' for k, v in rows)
             + "</table>")

    notes = list(content.get("notes") or [])
    if mode in ("A", "dual"):
        if cleaned:
            notes.insert(0, "본문은 자막 원문을 Claude가 문맥에 맞게 교정한 것입니다(오인식·맞춤법·띄어쓰기·문장부호). "
                            "내용을 줄이거나 보태지 않았지만 교정이 틀릴 수 있으니, 인용 전에는 문단 앞 시각(약 20초 단위)을 눌러 원본 영상을 확인하십시오. "
                            "(?)·[불명확]은 확인하지 못한 부분입니다.")
        elif tr.get("kind") == "auto":
            notes.insert(0, "본문은 유튜브 자동 생성 자막을 그대로 옮긴 것이라 고유명사·전문용어 오인식이 있을 수 있습니다.")
        if tr.get("kind") == "gemini":
            cov = tr.get("coverage")
            notes.insert(0, "원문 자막이 아니라 Gemini AI가 영상을 듣고 받아쓴 텍스트입니다. 누락·오기·없는 말이 섞일 수 있습니다."
                         + (f" 영상 길이 대비 전사 범위 약 {int(cov * 100)}%." if cov is not None else ""))
    if notes:
        inner = f'<p style="{BASE}font-size:10pt;font-weight:bold;margin-top:0;margin-bottom:4pt;">읽기 전에</p>'
        inner += "".join(f'<p style="{BASE}font-size:10pt;line-height:1.6;margin-top:0;margin-bottom:3pt;">• {e(n)}</p>'
                         for n in notes)
        b.append(p("", SMALL))
        b.append(box(inner, NOTE))

    n_h2 = 0

    # ---------- Mode B ----------
    if mode in ("B", "dual"):
        s = content.get("summary") or {}
        if not s.get("thesis"):
            die("mode B/dual에는 summary.thesis가 필요합니다")
        def h2b(text):
            nonlocal n_h2
            n_h2 += 1
            b.append(f'<h2 style="{H2}">{n_h2}. {e(text)}</h2>')

        h2b("핵심 명제")
        b.append(box("".join(f'<p style="{BASE}font-size:11pt;line-height:1.7;margin-top:0;margin-bottom:6pt;">{e(t)}</p>'
                             for t in s["thesis"]), CALLOUT))
        if s.get("logic_tree"):
            h2b("핵심 로직 트리")
            for n in s["logic_tree"]:
                lv = int(n.get("level", 0))
                mark = "" if lv == 0 else ("➔ " if lv == 1 else "↳ ")
                txt = f"<b>{e(n['text'])}</b>" if lv == 0 else e(n["text"])
                b.append(f'<p style="{P}margin-bottom:4pt;margin-left:{lv * 20}pt;">{mark}{txt}</p>')
        t = s.get("table")
        if t:
            h2b("핵심 요약표")
            b.append(f'<table style="{TABLE}"><tr>'
                     + "".join(f'<td style="{TH}">{e(h)}</td>' for h in t["headers"]) + "</tr>"
                     + "".join("<tr>" + "".join(f'<td style="{CELL}">{e(str(c))}</td>' for c in r) + "</tr>"
                               for r in t["rows"]) + "</table>")
        if s.get("points"):
            h2b("상세 논점")
            for pt in s["points"]:
                head = e(pt["title"])
                if pt.get("start") is not None and has_ts:
                    head += "  " + link(pt["start"], f"▶ {short(pt['start'], long_video)}", size="10pt")
                b.append(f'<h3 style="{H3}">{head}</h3>')
                b.append("<ul>" + "".join(f'<li style="{P}margin-bottom:4pt;">{e(i)}</li>' for i in pt["items"]) + "</ul>")

    # ---------- Mode A ----------
    if mode in ("A", "dual"):
        user_secs = bool(content.get("sections"))
        secs = content.get("sections") or [{"start": c["start"], "title": c["title"]} for c in meta.get("chapters") or []]
        if not secs:
            end = paras[-1][0]
            secs = [{"start": t, "title": f"구간 {i + 1}"} for i, t in enumerate(range(0, int(end) + 1, 300))]
        secs = sorted(secs, key=lambda x: x["start"])
        if secs[0]["start"] > paras[0][0]:
            secs.insert(0, {"start": 0, "title": "도입"})
        # 각 소제목이 시작되는 문단 번호: start(초) 이후 첫 문단. anchor가 있으면 그 말로 시작하는 문단.
        idx = []
        for sec in secs:
            lo = next((x for x in reversed(idx) if x is not None), 0)
            anchor = (sec.get("anchor") or "").strip()
            k = next((j for j in range(lo, len(paras)) if paras[j][0] >= sec["start"]
                      and (not anchor or paras[j][1].startswith(anchor))), None)
            if k is None and anchor:
                print(f"[주의] anchor '{anchor}' 를 못 찾아 시각({sec['start']}초) 기준으로 나눔", file=sys.stderr)
                k = next((j for j in range(lo, len(paras)) if paras[j][0] >= sec["start"]), None)
            if k is None and not user_secs:
                print(f"[주의] 챕터 '{sec['title']}' 에 해당하는 문단이 없어 건너뜀", file=sys.stderr)
                idx.append(None)
                continue
            if k is None:
                die(f"소제목 '{sec['title']}' 의 시작 문단을 찾지 못함 (start={sec['start']}, anchor='{anchor}')")
            idx.append(k)
        keep = [(sec, k) for sec, k in zip(secs, idx) if k is not None]
        keep[0] = (keep[0][0], 0)
        groups = [(sec, paras[k:(keep[i + 1][1] if i + 1 < len(keep) else len(paras))]) for i, (sec, k) in enumerate(keep)]
        for sec, g in groups:
            if not g:
                print(f"[주의] 소제목 '{sec['title']}' 이 다음 소제목과 같은 문단에서 시작해 빠짐 — anchor로 시작 문단을 지정할 것",
                      file=sys.stderr)
        groups = [(sec, g) for sec, g in groups if g]
        end_of = [groups[i + 1][1][0][0] if i + 1 < len(groups) else meta.get("duration") or g[-1][0]
                  for i, (_, g) in enumerate(groups)]

        if mode == "dual":
            n_h2 += 1
            b.append(f'<h2 style="{H2}">{n_h2}. 전문</h2>')
        sec_tag, sec_style = ("h3", H3.replace(f"color:{INK};", f"color:{ACCENT};")) if mode == "dual" else ("h2", H2)

        # 목차
        if len(groups) > 1:
            b.append(f'<{sec_tag} style="{sec_style}">목차</{sec_tag}>' if mode == "dual" else f'<h2 style="{H2}">목차</h2>')
            b.append(f'<table style="{TABLE}">' + "".join(
                f'<tr><td style="{TOC_TIME}">'
                + (link(g[0][0], short(g[0][0], long_video), color=MUTED) if has_ts else "")
                + f'</td><td style="{TOC_TITLE}"><span style="color:{ACCENT};font-weight:bold;">{i:02d}</span>'
                  f'&nbsp;&nbsp;{e(sec["title"])}</td></tr>'
                for i, (sec, g) in enumerate(groups, 1)) + "</table>")

        for i, (sec, g) in enumerate(groups, 1):
            b.append(f'<{sec_tag} style="{sec_style}">{i:02d}&nbsp;&nbsp;{e(sec["title"])}</{sec_tag}>')
            if has_ts:
                rng = f"{short(g[0][0], long_video)} – {short(end_of[i - 1], long_video)}"
                b.append(p(link(g[0][0], f"▶ {rng} 영상에서 보기", color=MUTED), SMALL + "margin-bottom:10pt;"))
            for t0, text in g:
                stamp = (link(t0, short(t0, long_video), color=FAINT, size="9pt") + "&nbsp;&nbsp;") if has_ts else ""
                b.append(p(stamp + e(text)))

        corr = [c for c in content.get("corrections") or [] if isinstance(c, (list, tuple)) and len(c) == 2]
        if len(corr) != len(content.get("corrections") or []):
            print("[주의] corrections 중 [원문, 교정] 두 칸이 아닌 항목은 뺐음", file=sys.stderr)
        if corr:
            b.append(f'<{sec_tag} style="{sec_style}">부록 · 주요 교정 어휘</{sec_tag}>' if mode == "dual"
                     else f'<h2 style="{H2}">부록 · 주요 교정 어휘</h2>')
            b.append(p("자막 원문에서 잘못 인식된 말을 어떻게 바로잡았는지 보여 줍니다.", SMALL + "margin-bottom:8pt;"))
            half = (len(corr) + 1) // 2
            cols = [corr[:half], corr[half:]]
            hdr = f'<td style="{TH}width:25%;">자막 원문</td><td style="{TH}width:25%;">교정</td>'
            body = ""
            for r in range(half):
                body += "<tr>"
                for col in cols:
                    if r < len(col):
                        body += f'<td style="{CELL}color:{MUTED};">{e(col[r][0])}</td><td style="{CELL}">{e(col[r][1])}</td>'
                    else:
                        body += f'<td style="{CELL}"></td><td style="{CELL}"></td>'
                body += "</tr>"
            b.append(f'<table style="{TABLE}"><tr>{hdr}{hdr}</tr>{body}</table>')

    today = datetime.date.today().strftime("%Y.%m.%d")
    b.append(p("", SMALL))
    b.append(p(e(f"youtube-archive v{VERSION} · {today} 아카이빙"), SMALL + f"color:{FAINT};font-size:8.5pt;margin-top:24pt;"))

    doc = ('<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
           f"<title>{e(title)}</title></head><body style=\"{BASE}font-size:11pt;\">" + "\n".join(b) + "</body></html>")
    data = entities(doc).encode("utf-8")
    out = work / "doc.html"
    out.write_bytes(data)  # write_text는 Windows에서 줄바꿈을 CRLF로 바꿔 해시가 어긋난다
    digest = hashlib.sha256(data).hexdigest()
    for w in clean_warns:
        print(f"[주의] {w}", file=sys.stderr)
    print(json.dumps({
        "title": title,
        "folder": cat["folder"],
        "folder_id": cat["folder_id"],
        "root_id": cats["root"]["id"],
        "html_path": str(out.resolve()),
        "html_bytes": len(data),
        "file_reference": f"sha256:{digest}:{out.resolve()}",
        "paragraphs_placed": len(paras) if mode != "B" else None,
        "cleaned": cleaned,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
