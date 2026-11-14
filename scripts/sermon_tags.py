#!/usr/bin/env python3
"""설교 활용 태그: content.json의 "sermon" 명세를 검사하고, 문서에 넣을 고정 표기로 바꾼다.

이 표는 나중에 Google Drive 전문 검색으로 설교 자료를 찾기 위한 것이라 라벨·표기가 글자 그대로 같아야 한다.
그래서 Claude는 구조만 쓰고 "본문: 히브리서 11:1 (히 11:1)" 같은 최종 문자열은 이 모듈이 만든다.

content.json:
"sermon": {
  "level": "상",                                   # 상 | 중 | 하 (설교연결도)
  "passages": [{"book": "히브리서", "ref": "11:1"}],  # 영상이 직접 언급·낭독한 구절만. book은 정식 명칭이나 약어
  "words": [{"word": "ὑπόστασις", "reading": "휘포스타시스"}],   # 영상이 언급한 히브리어·헬라어 단어만
  "topics": ["믿음", "소망"],                      # 신학주제, 최대 5개. TOPICS에서 우선 고른다
  "life": ["불안", "진로"],                        # 청년삶, 최대 5개. LIFE에서 우선 고른다
  "illustrations": [                               # 예화 카드, 상·중일 때만, 최대 3개
    {"title": "한 줄 제목", "scene": "2~3문장 장면", "facts": "숫자·연도·이름 (화자 주장이면 '(화자 주장)')",
     "start": 760, "topics": ["믿음"], "life": ["실패"]}
  ],
  "verify": ["검증이 필요한 주장 한 줄", ...],      # 없으면 []
  "caution": "없음"                                # 없음 | "[주의] 사유" | "[확인불가] 사유"
}
level이 "하"이면 level만 쓰고 나머지는 비워 둔다(표에는 "해당 없음"이 들어간다).
"""
import re
import unicodedata

LEVELS = ("상", "중", "하")
MAX_TAGS, MAX_CARDS = 5, 3

TOPICS = ("믿음 소망 사랑 은혜 구원 회개 성화 성령 기도 예배 말씀 교회 공동체 고난 악과고통 죄 용서 십자가 부활 종말 "
          "창조 섭리 소명 제자도 정의 하나님나라 이단분별").split()
LIFE = ("불안 진로 취업 일 돈 소비 주거 관계 연애 결혼 가족 외로움 비교 자존감 정체성 실패 회복 몸과건강 습관 시간 "
        "디지털 AI 공정 세대 죽음").split()

# 개역개정 정식 명칭과 약어
BOOKS = [
    ("창세기", "창"), ("출애굽기", "출"), ("레위기", "레"), ("민수기", "민"), ("신명기", "신"), ("여호수아", "수"),
    ("사사기", "삿"), ("룻기", "룻"), ("사무엘상", "삼상"), ("사무엘하", "삼하"), ("열왕기상", "왕상"), ("열왕기하", "왕하"),
    ("역대상", "대상"), ("역대하", "대하"), ("에스라", "스"), ("느헤미야", "느"), ("에스더", "에"), ("욥기", "욥"),
    ("시편", "시"), ("잠언", "잠"), ("전도서", "전"), ("아가", "아"), ("이사야", "사"), ("예레미야", "렘"),
    ("예레미야애가", "애"), ("에스겔", "겔"), ("다니엘", "단"), ("호세아", "호"), ("요엘", "욜"), ("아모스", "암"),
    ("오바댜", "옵"), ("요나", "욘"), ("미가", "미"), ("나훔", "나"), ("하박국", "합"), ("스바냐", "습"),
    ("학개", "학"), ("스가랴", "슥"), ("말라기", "말"),
    ("마태복음", "마"), ("마가복음", "막"), ("누가복음", "눅"), ("요한복음", "요"), ("사도행전", "행"), ("로마서", "롬"),
    ("고린도전서", "고전"), ("고린도후서", "고후"), ("갈라디아서", "갈"), ("에베소서", "엡"), ("빌립보서", "빌"),
    ("골로새서", "골"), ("데살로니가전서", "살전"), ("데살로니가후서", "살후"), ("디모데전서", "딤전"), ("디모데후서", "딤후"),
    ("디도서", "딛"), ("빌레몬서", "몬"), ("히브리서", "히"), ("야고보서", "약"), ("베드로전서", "벧전"), ("베드로후서", "벧후"),
    ("요한일서", "요일"), ("요한이서", "요이"), ("요한삼서", "요삼"), ("유다서", "유"), ("요한계시록", "계"),
]
BOOK_OF = {k: (n, a) for n, a in BOOKS for k in (n, a)}

REF = re.compile(r"^[1-9]\d{0,2}(?::[1-9]\d{0,2})?(?:[-,][1-9]\d{0,2}(?::[1-9]\d{0,2})?)*$")   # 11:1 · 22:1-14 · 5:3-6:2 · 23 · 1:1,3
DASHES = re.compile(r"[‐-―−~～〜]")      # 여러 대시·물결 → '-'
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
HEBREW = re.compile(r"[֐-׿]")
NIQQUD = re.compile(r"[ְ-ׇֽֿׁׂ]")
HANGUL = re.compile(r"[가-힣]")
CAUTION = re.compile(r"^(없음|\[주의\] \S.*|\[확인불가\] \S.*)$")

NA = "해당 없음"
LISTS = ("passages", "words", "topics", "life", "illustrations", "verify")


def nfc(x) -> str:
    """검색 표기가 바이트 단위로 같도록 NFC로 맞춘다(NFD 한글·헬라어 결합 문자 등)."""
    return unicodedata.normalize("NFC", str(x)).strip()


def _list(v, where, errs):
    if v is None:
        return []
    if not isinstance(v, list):
        errs.append(f"{where}는 목록([...])이어야 함 (지금 {type(v).__name__})")
        return []
    return v


def _tags(values, vocab, prefix, where, errs, warns):
    vals = []
    for v in values:
        v = re.sub(r"\s+", "", re.sub(rf"^{prefix}\s*:", "", nfc(v)))   # '주제 : 하나님 나라' → '하나님나라'
        if v and v not in vals:
            vals.append(v)
    if len(vals) > MAX_TAGS:
        errs.append(f"{where}: 최대 {MAX_TAGS}개 (지금 {len(vals)}개)")
    off = [v for v in vals if v not in vocab]
    if off:
        warns.append(f"{where}: 기준 어휘에 없는 말 {off} — 맞는 기준 어휘가 정말 없을 때만 새 말을 쓴다")
    return vals


def _join(prefix, vals):
    return "; ".join(f"{prefix}: {v}" for v in vals) if vals else "없음"


def build(sermon, duration=None, transcript_text=""):
    """(rows, cards, errors, warnings). rows: [(라벨, [줄, ...])], cards: [{title, scene, facts, start, link_tags}]"""
    errs, warns = [], []
    if not isinstance(sermon, dict):
        return [], [], ["content.json에 sermon(설교 활용 태그)이 없습니다 — 모든 문서에 필요합니다"], []
    level = nfc(sermon.get("level", ""))
    if level not in LEVELS:
        errs.append(f"sermon.level은 {'/'.join(LEVELS)} 중 하나 (지금 {sermon.get('level')!r})")
        return [], [], errs, warns
    lists = {k: _list(sermon.get(k), f"sermon.{k}", errs) for k in LISTS}
    caution = nfc(sermon.get("caution") or "없음")
    if not CAUTION.match(caution):
        errs.append(f"sermon.caution '{caution}' — '없음', '[주의] 사유', '[확인불가] 사유' 중 하나 형식")

    if level == "하":
        extra = [k for k in LISTS if lists[k]]
        if extra:
            errs.append(f"설교연결도 '하'에서는 나머지 칸을 비워 둔다(지금 채워진 것: {', '.join(extra)}) — "
                        "연결점이 있다면 level을 '중' 이상으로")
        rows = [("설교연결도", ["하"])] + [(k, [NA]) for k in ("관련본문", "원어", "신학주제", "청년삶", "예화후보", "확인필요")]
        rows.append(("출처주의", [caution if caution != "없음" else NA]))   # 이단·주의 표시는 '하'여도 남긴다
        return rows, [], errs, warns

    passages = []
    for i, ps in enumerate(lists["passages"]):
        if not isinstance(ps, dict):
            errs.append(f"passages[{i}]는 {{\"book\": \"히브리서\", \"ref\": \"11:1\"}} 형식이어야 함 (지금 {ps!r})")
            continue
        book = re.sub(r"\s+", "", nfc(ps.get("book", "")))
        ref = DASHES.sub("-", re.sub(r"\s+", "", nfc(ps.get("ref", ""))))
        ref = re.sub(r"[장편]$", "", ref)                       # '23편' · '11장' → '23' · '11'
        if book not in BOOK_OF:
            errs.append(f"passages[{i}].book '{book}' — 개역개정 정식 명칭이나 약어가 아님")
            continue
        if not REF.match(ref):
            errs.append(f"passages[{i}].ref '{ref}' — '11:1', '22:1-14', '23' 같은 형식이어야 함")
            continue
        name, abbr = BOOK_OF[book]
        stems = {name, re.sub(r"(복음|서|기)$", "", name)}       # '히브리서'·'히브리', '요한일서'·'요한일'
        if transcript_text and not any(x in transcript_text for x in stems):
            warns.append(f"관련본문 '{name}'이 자막에 보이지 않음 — 영상이 직접 언급한 구절만 적는다(자막 오인식이면 무시)")
        s = f"본문: {name} {ref} ({abbr} {ref})"
        if s not in passages:
            passages.append(s)

    words = []
    for i, w in enumerate(lists["words"]):
        if not isinstance(w, dict):
            errs.append(f"words[{i}]는 {{\"word\": \"원문\", \"reading\": \"한글 음역\"}} 형식이어야 함 (지금 {w!r})")
            continue
        word, reading = nfc(w.get("word", "")), nfc(w.get("reading", ""))
        if not (GREEK.search(word) or HEBREW.search(word)):
            errs.append(f"words[{i}] '{word}' — 히브리어·헬라어 원문 글자가 아님")
            continue
        if not HANGUL.search(reading):
            errs.append(f"words[{i}] '{word}' — reading(한글 음역)이 필요함")
            continue
        if HEBREW.search(word) and not NIQQUD.search(word):
            warns.append(f"원어 '{word}' — 히브리어에는 모음 부호(니쿠드)를 넣는다")
        s = f"원어: {word} ({reading})"
        if s not in words:
            words.append(s)

    topics = _tags(lists["topics"], TOPICS, "주제", "신학주제", errs, warns)
    life = _tags(lists["life"], LIFE, "삶", "청년삶", errs, warns)

    cards = []
    ills = lists["illustrations"]
    if len(ills) > MAX_CARDS:
        errs.append(f"예화 카드는 최대 {MAX_CARDS}개 (지금 {len(ills)}개)")
    for i, c in enumerate(ills[:MAX_CARDS]):
        if not isinstance(c, dict):
            errs.append(f"illustrations[{i}]는 {{title, scene, facts, start, topics, life}} 객체여야 함")
            continue
        miss = [k for k in ("title", "scene", "facts", "start") if c.get(k) in (None, "")]
        if miss:
            errs.append(f"illustrations[{i}]에 {', '.join(miss)} 가 없음")
            continue
        start = c["start"]
        if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0 or (duration and start > duration):
            errs.append(f"illustrations[{i}].start {start!r} — 영상 안의 초 단위 시각이어야 함")
            continue
        ct = _tags(_list(c.get("topics"), f"illustrations[{i}].topics", errs), TOPICS, "주제", f"예화 카드 {i + 1} 주제", errs, warns)
        cl = _tags(_list(c.get("life"), f"illustrations[{i}].life", errs), LIFE, "삶", f"예화 카드 {i + 1} 삶", errs, warns)
        link = "; ".join([f"주제: {v}" for v in ct] + [f"삶: {v}" for v in cl])
        if not link:
            warns.append(f"예화 카드 {i + 1}에 연결 가능 주제(topics·life)가 없음")
        cards.append({"title": nfc(c["title"]), "scene": nfc(c["scene"]),
                      "facts": nfc(c["facts"]), "start": int(start), "link_tags": link or "없음"})

    verify = [nfc(v) for v in lists["verify"] if nfc(v)]

    rows = [
        ("설교연결도", [level]),
        ("관련본문", ["; ".join(passages) or "없음"]),
        ("원어", ["; ".join(words) or "없음"]),
        ("신학주제", [_join("주제", topics)]),
        ("청년삶", [_join("삶", life)]),
        ("예화후보", [f"예화 {len(cards)}개" if cards else "없음"]),
        ("확인필요", verify or ["없음"]),
        ("출처주의", [caution]),
    ]
    return rows, cards, errs, warns
