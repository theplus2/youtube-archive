#!/usr/bin/env python3
"""content.json의 summary.visuals(다이어그램 명세) → PNG 이미지.

Google Docs의 HTML 가져오기는 SVG·CSS 도형을 버리지만 PNG data URI 이미지는 살린다.
그래서 다이어그램을 HTML/CSS로 그린 뒤 헤드리스 Chrome(또는 Edge)으로 찍어 PNG로 만들고,
build_doc.py가 data URI로 문서에 넣는다.

사용법(단독 미리보기):
    python3 scripts/render_visuals.py work/<VIDEO_ID>     # work/<ID>/visuals/*.png 생성

브라우저: 환경 변수 CHROME_PATH → Chrome → Edge → chromium 순으로 찾는다.

스타일(content.json의 summary.style):
  "note"  (기본) 손글씨 노트 — Poor Story 손글씨체, 형광펜 라벨, 손으로 그은 듯한 테두리, 점 모눈 배경.
          글꼴은 Google Fonts에서 불러오므로 인터넷이 필요하다(못 불러오면 오류).
  "clean" 깔끔한 도식 — Noto Sans KR, 색 면 상자.

자동 점검: 그림마다 같은 페이지를 한 번 더 열어(DOM 덤프) 상자 밖으로 삐져나온 글자, 겹친 순환 노드,
세 줄 이상으로 접힌 라벨, 가로 넘침을 찾아 경고로 돌려준다. 경고가 난 그림만 열어 보면 된다.

visuals 항목 공통: {"type": "...", "title": "제목", "caption": "한 줄 설명(선택)", "start": 초(선택)}
  tree      {"root": "주제", "branches": [{"label": "가지", "items": ["...", ...]}]}          2~5가지
  flow      {"steps": [{"label": "단계", "desc": "설명"}]}                                   2~7단계 (5개 이상은 세로)
  cycle     {"center": "가운데 말(선택)", "nodes": [{"label": "...", "desc": "..."}]}       2~6개, 화살표가 순환
  matrix    {"columns": ["열", ...], "rows": [{"label": "행", "icon": "🚗", "cells": ["...", ...]}]}
  contrast  {"left": {"label": "통념", "items": [...]}, "right": {"label": "실제", "items": [...]}, "middle": "→"}
  layers    {"layers": [{"label": "층", "desc": "설명"}]}     위(좁음) → 아래(넓음). 기초가 아래
  timeline  {"events": [{"time": "02:12", "label": "...", "desc": "..."}]}
  cards     {"cards": [{"icon": "💡", "label": "...", "desc": "..."}]}                      2~6장
"""
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WIDTH = 900          # CSS px. 2배율로 찍어 1800px PNG가 된다.
SCALE = 2
DOC_WIDTH_PX = 624   # 문서에 넣을 너비(px). Docs에서 468pt = 본문 폭 6.5in.

# 렌더러가 읽는 현재 스타일 값 (use_style()이 바꾼다)
PALETTE = TINTS = []
INK = MUTED = LINE = ARROW = ""
CSS = ""

e = html.escape

CLEAN = {
    "palette": ["#1f4e8c", "#0f7b6c", "#b8661a", "#a23b5d", "#5b4a9e", "#4d7c2a"],
    "tints": ["#eaf1fa", "#e5f4f1", "#fbf0e4", "#f8e9ee", "#efecf8", "#edf5e6"],
    "ink": "#202124", "muted": "#5f6368", "line": "#c7ccd4", "arrow": "#9aa3ae",
}
# 손글씨 노트: 펜 색(글자) — 형광펜은 같은 색을 옅게 섞어 만든다. 상자는 흰 바탕 + 손으로 그은 테두리
NOTE = {
    "palette": ["#d9467c", "#2f7fd1", "#3f9a5b", "#e0861b", "#8a5cd6", "#1f9aa0"],
    "tints": ["#ffffff"] * 6,
    "ink": "#33373d", "muted": "#6b7079", "line": "#33373d", "arrow": "#33373d",
    "font": "Poor Story",
}


def clean_css(t):
    P, LN = t["palette"], t["line"]
    return f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#ffffff}}
body{{width:{WIDTH}px;padding:28px 30px;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;color:{t["ink"]};
     font-size:17px;line-height:1.5;word-break:keep-all;overflow-wrap:anywhere}}
.box{{border-radius:12px;padding:14px 16px}}
.lbl{{font-weight:700;font-size:19px;line-height:1.35}}
.desc{{font-size:15.5px;color:#3c4043;margin-top:6px;line-height:1.5}}
ul{{list-style:none}}
li{{position:relative;padding-left:14px;margin-top:6px;font-size:15.5px;line-height:1.45;color:#3c4043}}
li:before{{content:"";position:absolute;left:0;top:10px;width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.55}}
/* tree */
.root{{margin:0 auto;width:fit-content;max-width:70%;text-align:center;background:{P[0]};color:#fff;
      font-size:22px;font-weight:700;padding:14px 26px;border-radius:14px}}
.stem{{width:2px;height:22px;background:{LN};margin:0 auto}}
.kids{{display:grid;gap:14px;position:relative;padding-top:22px}}
.kids:before{{content:"";position:absolute;top:0;height:2px;background:{LN}}}
.kid{{position:relative}}
.kid:before{{content:"";position:absolute;top:-22px;left:50%;width:2px;height:22px;background:{LN}}}
.kid .head{{color:#fff;text-align:center;font-weight:700;font-size:17.5px;padding:10px 10px;border-radius:10px 10px 0 0}}
.kid .body{{padding:6px 12px 12px;border-radius:0 0 10px 10px;min-height:40px}}
/* flow */
.flow-h{{display:flex;align-items:stretch}}
.flow-h .step{{flex:1;display:flex;flex-direction:column}}
.arrow-h{{flex:0 0 34px;display:flex;align-items:center;justify-content:center}}
.num{{display:inline-flex;width:30px;height:30px;border-radius:50%;color:#fff;font-weight:700;font-size:16px;
     align-items:center;justify-content:center;margin-bottom:8px}}
.flow-v .step{{display:flex;gap:14px;align-items:flex-start}}
.flow-v .step .num{{flex:0 0 34px;height:34px;margin:6px 0 0}}
.flow-v .arrow-v{{height:26px;display:flex;justify-content:flex-start;padding-left:4px}}
/* cycle */
.cyc{{position:relative;width:100%}}
.cyc .node{{position:absolute;transform:translate(-50%,-50%);text-align:center;border-radius:14px;padding:12px 14px;
          box-shadow:0 0 0 2px #fff}}
.cyc .center{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;font-weight:700;
            font-size:19px;color:{t["muted"]};max-width:230px}}
/* matrix */
table{{border-collapse:separate;border-spacing:6px;width:100%;table-layout:fixed}}
th{{color:#fff;font-size:16.5px;padding:10px 8px;border-radius:9px;text-align:center}}
td{{font-size:15px;line-height:1.45;padding:10px 12px;border-radius:9px;vertical-align:top;color:#3c4043}}
td.rh{{background:#f1f3f4;color:{t["ink"]};font-weight:700;font-size:16px;text-align:center;vertical-align:middle}}
.ic{{font-size:26px;display:block;line-height:1.2;margin-bottom:2px}}
/* contrast */
.vs{{display:flex;align-items:stretch;gap:0}}
.vs .side{{flex:1}}
.vs .mid{{flex:0 0 64px;display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:700;color:{t["muted"]}}}
/* layers */
.layer{{margin:0 auto 8px;text-align:center;border-radius:10px;padding:12px 18px;color:#fff}}
.layer .desc{{color:rgba(255,255,255,.92)}}
/* timeline */
.tl{{position:relative;padding-left:120px}}
.tl:before{{content:"";position:absolute;left:96px;top:8px;bottom:8px;width:3px;background:{LN};border-radius:2px}}
.ev{{position:relative;margin-bottom:16px}}
.ev .t{{position:absolute;left:-120px;width:80px;text-align:right;font-weight:700;color:{t["muted"]};font-size:15.5px;top:2px}}
.ev .dot{{position:absolute;left:-31px;top:6px;width:15px;height:15px;border-radius:50%;border:3px solid #fff}}
/* cards */
.cards{{display:grid;gap:14px}}
.card{{border-radius:14px;padding:16px 16px 18px;border-top:5px solid}}
.card .ic{{font-size:34px;margin-bottom:6px}}
"""


def note_css(t):
    INKN, FONT = t["ink"], t["font"]
    HL = "color-mix(in srgb, currentColor 26%, white)"   # 펜 색을 옅게 섞은 형광펜
    YEL = "#ffe36e"
    R = "url(#rough)"                                     # 손으로 그은 듯 흔드는 SVG 필터
    BOXES = ".box,.kid .body,.card,.side,td:not(.rh),.layer,.root,.cyc .node"
    return f"""
@import url('https://fonts.googleapis.com/css2?family={FONT.replace(" ", "+")}&display=block');
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#ffffff}}
body{{width:{WIDTH}px;padding:18px 20px;font-family:'{FONT}','Noto Sans KR',cursive;color:{INKN};font-size:22px;
     line-height:1.35;letter-spacing:-0.03em;word-break:keep-all;overflow-wrap:anywhere}}
.paper{{padding:26px;border-radius:6px;background:#fff radial-gradient(#d5dae1 1.2px, transparent 1.5px) 0 0/24px 24px}}
/* 테두리는 ::after에만 필터를 걸어 글자는 흔들리지 않게 */
.box,.kid .body,.card,.side,td,th,.layer,.root,.cyc .node{{position:relative;background:transparent!important;
     border:none!important;box-shadow:none!important}}
{", ".join(x + ":after" for x in BOXES.split(","))}{{content:"";position:absolute;inset:0;border:2.2px solid #4b5059;
     border-radius:14px;filter:{R};pointer-events:none}}
.lbl{{display:inline;-webkit-box-decoration-break:clone;box-decoration-break:clone;font-weight:700;font-size:25px;
      line-height:1.45;padding:0 3px;background:linear-gradient(transparent 52%, {HL} 52%, {HL} 92%, transparent 92%)}}
.desc{{display:block;font-size:21px;color:#4a4f57;margin-top:6px;line-height:1.35}}
ul{{list-style:none}}
li{{position:relative;padding-left:18px;margin-top:5px;font-size:21px;line-height:1.3;color:#4a4f57}}
li:before{{content:"▸";position:absolute;left:0;top:0;font-size:17px;color:currentColor;opacity:.9}}
svg path{{filter:{R}}}
/* tree */
.root{{margin:0 auto;width:fit-content;max-width:75%;text-align:center;color:{INKN};font-size:30px;font-weight:700;padding:12px 28px}}
.root:after{{border-width:3px;border-radius:40px}}
.stem{{width:2.6px;height:24px;background:{INKN};margin:0 auto;filter:{R}}}
.kids{{display:grid;gap:18px;position:relative;padding-top:24px}}
.kids:before{{content:"";position:absolute;top:0;height:2.6px;background:{INKN};filter:{R}}}
.kid{{position:relative}}
.kid:before{{content:"";position:absolute;top:-24px;left:50%;width:2.6px;height:24px;background:{INKN};filter:{R}}}
.kid .head{{display:table;margin:0 auto 8px;color:{INKN};font-weight:700;font-size:26px;padding:0 6px;
           background:linear-gradient(transparent 50%, {YEL} 50%, {YEL} 92%, transparent 92%)!important}}
.kid .body{{padding:8px 14px 14px;min-height:40px}}
/* flow */
.flow-h{{display:flex;align-items:stretch}}
.flow-h .step{{flex:1;display:flex;flex-direction:column}}
.arrow-h{{flex:0 0 40px;display:flex;align-items:center;justify-content:center}}
.box{{padding:14px 16px}}
.flow-h .step > .lbl{{align-self:flex-start}}
.num{{display:inline-flex;width:34px;height:34px;border-radius:50%;background:transparent!important;color:{INKN};
      font-weight:700;font-size:21px;align-items:center;justify-content:center;margin-bottom:6px;border:2.4px solid {INKN};filter:{R}}}
.flow-v .step{{display:flex;gap:14px;align-items:flex-start}}
.flow-v .step .num{{flex:0 0 36px;height:36px;margin:8px 0 0}}
.flow-v .arrow-v{{height:30px;display:flex;justify-content:flex-start;padding-left:5px}}
/* cycle */
.cyc{{position:relative;width:100%}}
.cyc .node{{position:absolute;transform:translate(-50%,-50%);text-align:center;padding:12px 14px;background:#fff!important}}
.cyc .center{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;font-weight:700;
            font-size:24px;color:{t["muted"]};max-width:230px}}
/* matrix */
table{{border-collapse:separate;border-spacing:8px;width:100%;table-layout:fixed}}
th{{color:{INKN}!important;font-size:23px;padding:6px 8px;text-align:center;font-weight:700}}
td{{font-size:20px;line-height:1.3;padding:10px 12px;vertical-align:top;color:#4a4f57}}
td.rh{{color:{INKN};font-weight:700;font-size:22px;text-align:center;vertical-align:middle;
      background:linear-gradient(transparent 55%, {YEL} 55%, {YEL} 90%, transparent 90%)!important}}
.ic{{font-size:28px;display:block;line-height:1.2;margin-bottom:2px}}
/* contrast */
.vs{{display:flex;align-items:stretch}}
.vs .side{{flex:1;padding:14px 18px;text-align:center}}
.vs .side ul{{text-align:left;margin-top:4px}}
.vs .mid{{flex:0 0 70px;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:700;color:{t["muted"]}}}
/* layers */
.layer{{margin:0 auto 10px;text-align:center;padding:12px 18px;color:{INKN}!important}}
.layer .desc{{color:#4a4f57}}
{chr(10).join(f".layer:nth-child(6n+{i + 1}) .lbl{{color:{c}}}" for i, c in enumerate(t["palette"]))}
/* timeline */
.tl{{position:relative;padding-left:130px}}
.tl:before{{content:"";position:absolute;left:104px;top:10px;bottom:10px;width:2.6px;background:{INKN};filter:{R}}}
.ev{{position:relative;margin-bottom:16px}}
.ev .t{{position:absolute;left:-134px;width:90px;text-align:right;font-weight:700;color:{INKN};font-size:23px;top:6px}}
.ev .dot{{position:absolute;left:-34px;top:12px;width:16px;height:16px;border-radius:50%;border:2.4px solid {INKN};filter:{R}}}
/* cards */
.cards{{display:grid;gap:16px}}
.card{{padding:14px 16px 18px}}
.card .ic{{font-size:34px;margin-bottom:4px}}
"""


ROUGH_FILTER = ('<svg width="0" height="0" style="position:absolute"><filter id="rough" x="-5%" y="-5%" width="110%" height="110%">'
                '<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7"/>'
                '<feDisplacementMap in="SourceGraphic" scale="3.2" xChannelSelector="R" yChannelSelector="G"/></filter></svg>')

STYLES = {"note": (NOTE, note_css), "clean": (CLEAN, clean_css)}
DEFAULT_STYLE = "note"


def use_style(name):
    """렌더러가 읽는 전역 색·CSS를 바꾼다."""
    global PALETTE, TINTS, INK, MUTED, LINE, ARROW, CSS
    if name not in STYLES:
        raise ValueError(f"summary.style '{name}' 는 지원하지 않음 ({', '.join(STYLES)})")
    t, css = STYLES[name]
    PALETTE, TINTS = t["palette"], t["tints"]
    INK, MUTED, LINE, ARROW = t["ink"], t["muted"], t["line"], t["arrow"]
    CSS = css(t)
    return t


use_style("clean")


def arrow_svg(direction="right", color=None, size=30):
    color = color or LINE
    if direction == "right":
        return (f'<svg width="{size}" height="{size}" viewBox="0 0 30 30"><path d="M4 15h18M15 7l8 8-8 8" '
                f'fill="none" stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 30 30"><path d="M15 3v20M7 15l8 8 8-8" '
            f'fill="none" stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def items_html(items):
    return "<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in items or []) + "</ul>"


def r_tree(v):
    br = v["branches"]
    n = len(br)
    edge = f"calc((100% - {(n - 1) * 14}px) / {2 * n})"  # 첫·끝 가지의 가운데 (gap 14px)
    out = f'<div class="root">{e(v["root"])}</div><div class="stem"></div>'
    out += (f'<div class="kids" style="grid-template-columns:repeat({n},1fr)">'
            f'<style>.kids:before{{left:{edge};right:{edge}}}</style>')
    for i, b in enumerate(br):
        c, t = PALETTE[i % 6], TINTS[i % 6]
        out += (f'<div class="kid"><div class="head" style="background:{c}">{e(b["label"])}</div>'
                f'<div class="body" style="background:{t};color:{c}">{items_html(b.get("items"))}</div></div>')
    return out + "</div>"


def r_flow(v):
    steps = v["steps"]
    if len(steps) <= 4:
        parts = []
        for i, s in enumerate(steps):
            c, t = PALETTE[i % 6], TINTS[i % 6]
            parts.append(f'<div class="step box" style="background:{t}"><div><span class="num" style="background:{c}">{i + 1}</span></div>'
                         f'<div class="lbl" style="color:{c}">{e(s["label"])}</div>'
                         + (f'<div class="desc">{e(s["desc"])}</div>' if s.get("desc") else "") + "</div>")
        return '<div class="flow-h">' + f'<div class="arrow-h">{arrow_svg()}</div>'.join(parts) + "</div>"
    parts = []
    for i, s in enumerate(steps):
        c, t = PALETTE[i % 6], TINTS[i % 6]
        parts.append(f'<div class="step"><span class="num" style="background:{c}">{i + 1}</span>'
                     f'<div class="box" style="background:{t};flex:1"><div class="lbl" style="color:{c}">{e(s["label"])}</div>'
                     + (f'<div class="desc">{e(s["desc"])}</div>' if s.get("desc") else "") + "</div></div>")
    return '<div class="flow-v">' + f'<div class="arrow-v">{arrow_svg("down", size=26)}</div>'.join(parts) + "</div>"


def r_cycle(v):
    nodes = v["nodes"]
    n = len(nodes)
    W = WIDTH - 60
    H = 470 if n <= 3 else 560
    cx, cy = W / 2, H / 2
    rx, ry = (W / 2 - 150), (H / 2 - 75)
    nw = 230 if n <= 4 else 190
    start = math.pi if n == 2 else -math.pi / 2
    angs = [start + 2 * math.pi * i / n for i in range(n)]
    pts = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in angs]
    gap = 0.62 if n <= 3 else (0.5 if n == 4 else 0.34)
    paths = ""
    for i in range(n):
        a0, a1 = angs[i] + gap, angs[i] + 2 * math.pi / n - gap
        steps = 24
        d = ""
        for k in range(steps + 1):
            a = a0 + (a1 - a0) * k / steps
            x, y = cx + (rx + 8) * math.cos(a), cy + (ry + 8) * math.sin(a)
            d += ("M" if k == 0 else "L") + f"{x:.1f},{y:.1f} "
        paths += f'<path d="{d}" fill="none" stroke="{ARROW}" stroke-width="4" marker-end="url(#ah)"/>'
    svg = (f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0"><defs>'
           f'<marker id="ah" markerWidth="12" markerHeight="12" refX="6" refY="6" orient="auto" markerUnits="userSpaceOnUse">'
           f'<path d="M0,0 L12,6 L0,12 z" fill="{ARROW}"/></marker></defs>{paths}</svg>')
    out = f'<div class="cyc" style="height:{H}px">{svg}'
    if v.get("center"):
        out += f'<div class="center">{e(v["center"])}</div>'
    for i, (nd, (x, y)) in enumerate(zip(nodes, pts)):
        c, t = PALETTE[i % 6], TINTS[i % 6]
        out += (f'<div class="node" style="left:{x:.0f}px;top:{y:.0f}px;width:{nw}px;background:{t};border:2px solid {c}">'
                f'<div class="lbl" style="color:{c}">{e(nd["label"])}</div>'
                + (f'<div class="desc">{e(nd["desc"])}</div>' if nd.get("desc") else "") + "</div>")
    return out + "</div>"


def r_matrix(v):
    cols = v["columns"]
    head = '<tr><th style="background:transparent"></th>' + "".join(
        f'<th style="background:{PALETTE[i % 6]}">{e(c)}</th>' for i, c in enumerate(cols)) + "</tr>"
    body = ""
    for r in v["rows"]:
        ic = f'<span class="ic">{e(r["icon"])}</span>' if r.get("icon") else ""
        body += f'<tr><td class="rh">{ic}{e(r["label"])}</td>' + "".join(
            f'<td style="background:{TINTS[i % 6]}">{e(str(x))}</td>' for i, x in enumerate(r["cells"])) + "</tr>"
    w = 20 if len(cols) >= 3 else 24
    return f'<table><colgroup><col style="width:{w}%"></colgroup>{head}{body}</table>'


def r_contrast(v):
    def side(s, c, t):
        return (f'<div class="side box" style="background:{t};border:2px solid {c}">'
                f'<div class="lbl" style="color:{c};text-align:center;margin-bottom:4px">{e(s["label"])}</div>'
                f'<div style="color:{c}">{items_html(s.get("items"))}</div></div>')
    mid = v.get("middle", "→")
    mid_html = arrow_svg(color="#9aa0a6", size=40) if mid == "→" else e(mid)
    return (f'<div class="vs">{side(v["left"], "#80868b", "#f1f3f4")}<div class="mid">{mid_html}</div>'
            f'{side(v["right"], PALETTE[0], TINTS[0])}</div>')


def r_layers(v):
    ls = v["layers"]
    n = len(ls)
    out = ""
    for i, l in enumerate(ls):
        w = 52 + 48 * (i / max(n - 1, 1))
        out += (f'<div class="layer" style="width:{w:.0f}%;background:{PALETTE[i % 6]}"><div class="lbl">{e(l["label"])}</div>'
                + (f'<div class="desc">{e(l["desc"])}</div>' if l.get("desc") else "") + "</div>")
    return out


def r_timeline(v):
    out = '<div class="tl">'
    for i, ev in enumerate(v["events"]):
        c, t = PALETTE[i % 6], TINTS[i % 6]
        out += (f'<div class="ev"><div class="t">{e(ev.get("time", ""))}</div><div class="dot" style="background:{c}"></div>'
                f'<div class="box" style="background:{t}"><div class="lbl" style="color:{c}">{e(ev["label"])}</div>'
                + (f'<div class="desc">{e(ev["desc"])}</div>' if ev.get("desc") else "") + "</div></div>")
    return out + "</div>"


def r_cards(v):
    cs = v["cards"]
    ncol = 3 if len(cs) in (3, 5, 6) else 2
    out = f'<div class="cards" style="grid-template-columns:repeat({ncol},1fr)">'
    for i, c in enumerate(cs):
        col, t = PALETTE[i % 6], TINTS[i % 6]
        out += (f'<div class="card" style="background:{t};border-top-color:{col}">'
                + (f'<span class="ic">{e(c["icon"])}</span>' if c.get("icon") else "")
                + f'<div class="lbl" style="color:{col}">{e(c["label"])}</div>'
                + (f'<div class="desc">{e(c["desc"])}</div>' if c.get("desc") else "") + "</div>")
    return out + "</div>"


RENDERERS = {"tree": r_tree, "flow": r_flow, "cycle": r_cycle, "matrix": r_matrix, "contrast": r_contrast,
             "layers": r_layers, "timeline": r_timeline, "cards": r_cards}
REQUIRED = {"tree": ("root", "branches"), "flow": ("steps",), "cycle": ("nodes",), "matrix": ("columns", "rows"),
            "contrast": ("left", "right"), "layers": ("layers",), "timeline": ("events",), "cards": ("cards",)}


def validate(v, i):
    t = v.get("type")
    if t not in RENDERERS:
        return f"visuals[{i}].type '{t}' 는 지원하지 않음 ({', '.join(RENDERERS)})"
    miss = [k for k in REQUIRED[t] if not v.get(k)]
    if miss:
        return f"visuals[{i}] ({t}) 에 {', '.join(miss)} 가 없음"
    if t == "matrix" and any(len(r.get("cells", [])) != len(v["columns"]) for r in v["rows"]):
        return f"visuals[{i}] (matrix) 의 행마다 cells 개수가 columns 개수와 같아야 함"
    return None


def find_browser():
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for c in cands:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    return None


# 그림을 그린 뒤 같은 페이지에서 레이아웃 문제를 찾아 #diag 에 JSON으로 적는다(--dump-dom으로 읽음).
DIAG_JS = r"""
(async () => {
  await document.fonts.ready;
  const W = [], txt = el => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 24);
  const font = document.body.dataset.font;
  if (font) {   // fonts.check()는 글꼴이 아예 등록 안 돼도 true라서, 실제로 받아진 FontFace가 있는지 직접 본다
    try { await document.fonts.load('24px "' + font + '"', document.body.innerText); } catch (err) {}
    const ok = [...document.fonts].some(f => f.family.replace(/["']/g, "") === font && f.status === "loaded");
    if (!ok) W.push("FONT:" + font);
  }
  const textRect = el => { const r = document.createRange(); r.selectNodeContents(el); return r; };
  if (document.body.scrollWidth > document.body.clientWidth + 1) W.push("그림이 가로로 넘침");
  document.querySelectorAll(".box,.kid .body,.card,.side,td,th,.layer,.root,.cyc .node,.kid .head").forEach(box => {
    const r = box.getBoundingClientRect(), q = textRect(box).getBoundingClientRect();   // 글자만 든 상자도 잰다
    if (q.width && (q.right > r.right + 2 || q.left < r.left - 2 || q.bottom > r.bottom + 2 || q.top < r.top - 2))
      W.push("상자 밖으로 글자가 나감: " + txt(box));
  });
  document.querySelectorAll(".lbl").forEach(l => {   // block·inline 모두: 글자 줄의 서로 다른 높이 수
    const tops = new Set([...textRect(l).getClientRects()].filter(x => x.width).map(x => Math.round(x.top / 4)));
    if (tops.size > 2) W.push("라벨이 세 줄 이상: " + txt(l));
  });
  const host = document.querySelector(".cyc");
  const nodes = [...document.querySelectorAll(".cyc .node")].map(n => [n, n.getBoundingClientRect()]);
  nodes.forEach(([n, a], i) => {
    nodes.slice(i + 1).forEach(([m, b]) => {
      if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) W.push("순환 노드가 겹침: " + txt(n) + " / " + txt(m));
    });
    const h = host.getBoundingClientRect();
    if (a.left < h.left - 2 || a.right > h.right + 2 || a.top < h.top - 2 || a.bottom > h.bottom + 2) W.push("순환 노드가 그림 밖: " + txt(n));
  });
  document.getElementById("diag").textContent = JSON.stringify([...new Set(W)]);
})();
"""


def page_html(v, style=DEFAULT_STYLE):
    t = use_style(style)
    body = RENDERERS[v["type"]](v)
    if style == "note":
        body = ROUGH_FILTER + f'<div class="paper">{body}</div>'
    font = f' data-font="{e(t["font"])}"' if t.get("font") else ""
    return (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body{font}>{body}<div id="diag" style="display:none"></div><script>{DIAG_JS}</script></body></html>')


def chrome(browser, td, height, *args):
    return [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={Path(td) / 'profile'}",
            f"--force-device-scale-factor={SCALE}", f"--window-size={WIDTH},{height}",
            "--virtual-time-budget=4000", *args]


DIAG_MISSING = "자동 점검 결과를 읽지 못함 — PNG를 직접 열어 확인할 것"


def diagnose(browser, src: Path, td, height):
    """같은 페이지의 DOM을 덤프해 점검 결과(경고 목록)를 읽는다."""
    r = subprocess.run(chrome(browser, td, height, "--dump-dom", src.as_uri()),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r'<div id="diag"[^>]*>(.*?)</div>', r.stdout or "", re.S)
    if not m or not m[1].strip():
        return [DIAG_MISSING]
    warns = json.loads(html.unescape(m[1]))
    font = [w for w in warns if w.startswith("FONT:")]
    if font:
        raise RuntimeError(f"손글씨 글꼴 '{font[0][5:]}'을(를) 불러오지 못함 — 인터넷 연결을 확인하거나 "
                           "content.json의 summary.style을 \"clean\"으로 바꿀 것")
    return warns


def trim(png: Path):
    from PIL import Image, ImageChops
    im = Image.open(png).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bbox = ImageChops.difference(im, bg).getbbox()
    if not bbox:
        raise RuntimeError("빈 이미지가 찍힘")
    pad = 24 * SCALE
    top, bottom = max(bbox[1] - pad, 0), min(bbox[3] + pad, im.height)
    if bottom >= im.height - 2:
        raise RuntimeError("다이어그램이 창 높이를 넘음")
    im.crop((0, top, im.width, bottom)).save(png, optimize=True)
    return im.width, bottom - top


def render_one(v, out: Path, browser: str, style=DEFAULT_STYLE):
    """PNG를 찍고 (너비, 높이, 경고 목록)을 돌려준다."""
    html_doc = page_html(v, style)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "v.html"
        src.write_text(html_doc, encoding="utf-8")
        for height in (2400, 5200):
            r = subprocess.run(chrome(browser, td, height, f"--screenshot={out.resolve()}", src.as_uri()),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if not out.exists():
                raise RuntimeError("브라우저가 스크린샷을 만들지 못함: " + (r.stderr or "")[-400:])
            try:
                w, h = trim(out)
            except RuntimeError as err:
                if "창 높이" not in str(err):
                    raise
                continue
            try:
                warns = diagnose(browser, src, td, height)
            except RuntimeError:
                out.unlink(missing_ok=True)     # 글꼴이 빠진 그림은 캐시하지 않는다
                raise
            return w, h, warns
        raise RuntimeError("다이어그램이 너무 김 — 항목을 줄이거나 나눌 것")


def render_all(visuals, out_dir: Path, style=DEFAULT_STYLE):
    """[(png_path, width_px, height_px, 경고 목록)] — 명세·스타일이 같으면 다시 찍지 않는다."""
    if style not in STYLES:
        raise ValueError(f"summary.style '{style}' 는 지원하지 않음 ({', '.join(STYLES)})")
    errs = [m for i, v in enumerate(visuals) if (m := validate(v, i))]
    if errs:
        raise ValueError("; ".join(errs))
    browser = find_browser()
    if not browser:
        raise RuntimeError("Chrome/Edge를 찾지 못함 (CHROME_PATH 환경 변수로 지정 가능)")
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for i, v in enumerate(visuals, 1):
        # 명세·스타일이나 이 렌더러 코드가 바뀌면 다시 찍는다
        key = hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True).encode("utf-8")
                             + style.encode() + Path(__file__).read_bytes()).hexdigest()[:12]
        png = out_dir / f"{i:02d}_{v['type']}_{key}.png"
        side = png.with_suffix(".json")              # 점검 결과
        if png.exists() and side.exists():
            from PIL import Image
            w, h = Image.open(png).size
            warns = json.loads(side.read_text(encoding="utf-8"))
        else:
            for old in list(out_dir.glob(f"{i:02d}_*.png")) + list(out_dir.glob(f"{i:02d}_*.json")):
                old.unlink()
            w, h, warns = render_one(v, png, browser, style)
            if DIAG_MISSING not in warns:            # 점검을 못 했으면 캐시하지 않아 다음에 다시 점검한다
                side.write_text(json.dumps(warns, ensure_ascii=False), encoding="utf-8")
        res.append((png, w, h, warns))
    return res


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python3 scripts/render_visuals.py work/<VIDEO_ID>")
    work = Path(sys.argv[1])
    content = json.loads((work / "content.json").read_text(encoding="utf-8"))
    summary = content.get("summary") or {}
    visuals = summary.get("visuals") or []
    if not visuals:
        sys.exit("summary.visuals 가 비어 있음")
    n = 0
    for png, w, h, warns in render_all(visuals, work / "visuals", summary.get("style", DEFAULT_STYLE)):
        print(f"{png}  {w}x{h}" + ("  [점검 경고]" if warns else "  [점검 통과]"))
        for m in warns:
            print(f"    - {m}")
        n += bool(warns)
    print(f"점검: {len(visuals)}개 중 {n}개 경고" + (" — 경고 난 그림만 열어 확인할 것" if n else " — 모두 통과"))


if __name__ == "__main__":
    main()
