#!/usr/bin/env python3
"""사람마다 다른 Google Drive 폴더 ID를 관리한다.

config/categories.json 은 모두가 같이 쓰는 카테고리 정의(이름·폴더명·범위)다.
Drive 폴더 ID는 사람마다 다르므로 git에 올리지 않는 config/drive.local.json 에 둔다.
저장소를 처음 받은 사람은 이 파일이 없어도 되며, 첫 아카이빙 때 Claude가 루트·카테고리 폴더를
찾거나 만들어 여기에 기록한다.

사용법:
    python3 scripts/drive_ids.py show                       # 루트·카테고리 폴더 ID와 빠진 것
    python3 scripts/drive_ids.py set-root <폴더ID>           # 아카이브 루트 폴더
    python3 scripts/drive_ids.py set <카테고리명> <폴더ID>    # 예: set "영화&드라마" 1abc...

drive.local.json:
    {"root_id": "...", "folders": {"신학&교회": "...", ...}}
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "config" / "drive.local.json"
CATS = ROOT / "config" / "categories.json"
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def categories():
    return json.loads(CATS.read_text(encoding="utf-8"))


def load():
    """{"root_id": str|None, "folders": {카테고리명: id}}. 파일이 없으면 빈 설정."""
    if not LOCAL.exists():
        return {"root_id": None, "folders": {}}
    data = json.loads(LOCAL.read_text(encoding="utf-8"))
    return {"root_id": data.get("root_id"), "folders": dict(data.get("folders") or {})}


def save(data):
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def die(msg):
    print(f"[오류] {msg}", file=sys.stderr)
    sys.exit(1)


def check_id(fid):
    if not DRIVE_ID.match(fid):
        die(f"'{fid}' 는 Drive 폴더 ID 형식이 아닙니다(링크가 아니라 ID만: folders/ 뒤의 글자).")
    return fid


def main():
    args = sys.argv[1:]
    cats = categories()
    names = [c["name"] for c in cats["categories"]]
    data = load()
    if args[:1] == ["show"] and len(args) == 1:
        print(json.dumps({
            "local_file": str(LOCAL), "exists": LOCAL.exists(),
            "root_title": cats["root"]["title"], "root_id": data["root_id"],
            "folders": {n: data["folders"].get(n) for n in names},
            "missing": [n for n in names if not data["folders"].get(n)],
        }, ensure_ascii=False, indent=2))
    elif args[:1] == ["set-root"] and len(args) == 2:
        if data["root_id"] and data["root_id"] != args[1] and data["folders"]:
            print("[주의] 루트가 바뀌어 기존 카테고리 폴더 ID를 비웁니다(새 루트 아래에서 다시 찾거나 만든다).", file=sys.stderr)
            data["folders"] = {}
        data["root_id"] = check_id(args[1])
        save(data)
        print(f"루트 폴더 ID 기록: {data['root_id']}")
    elif args[:1] == ["set"] and len(args) == 3:
        if args[1] not in names:
            die(f"카테고리 '{args[1]}' 가 없습니다: {', '.join(names)}")
        if not data["root_id"]:
            die("루트 폴더 ID가 먼저 필요합니다: set-root <폴더ID>")
        data["folders"][args[1]] = check_id(args[2])
        save(data)
        print(f"'{args[1]}' 폴더 ID 기록: {args[2]}")
    else:
        die("사용법: drive_ids.py show | set-root <ID> | set <카테고리명> <ID>")


if __name__ == "__main__":
    main()
