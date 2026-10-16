#!/usr/bin/env python3
"""
build_deck.py  --  normalize project logos, validate content, scan for leaks,
                   and bundle everything into assets/js/registry.js.

Each project lives in projects/<id>/ :
    source.png     original logo (any size; black background)   <- you edit
    project.json   content                                       <- you edit
    logo.webp      1600x1000 normalized hero                     <- generated
    thumb.webp      480x300  normalized gallery card             <- generated

Normalization never stretches or crops artwork: the logo is trimmed to its
visible content, given a uniform margin, and centred on a pure-black 16:10
canvas. All sources are on #000, so the padding is invisible.

Usage:
    python tools/build_deck.py            # build (fails on errors)
    python tools/build_deck.py --check    # validate + leak-scan only, write nothing

Requires: Pillow
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT / "projects"
REGISTRY = ROOT / "assets" / "js" / "registry.js"

HERO = (1600, 1000)
THUMB = (480, 300)
MARGIN = 0.07          # fraction of canvas kept clear on every side
LUMA_FLOOR = 14        # pixels darker than this count as background when trimming

INTRO_KEYS = ("problem", "value", "approach", "goals")
STATUSES = {"active", "planning", "paused", "complete"}
TL_STATES = {"done", "active", "next"}
OPEN_KINDS = {"question", "lesson", "gap"}
LIT_KEYS = ("category", "authors", "year", "title", "venue", "url")
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

# --- public-face leak scan --------------------------------------------------
# Anything matching these must not reach a public repo. Extend freely.
LEAK_PATTERNS = [
    (r"/eos/|/afs/|atlng\d*|lxplus", "internal host / filesystem path"),
    (r"[A-Za-z]:\\\\|/home/\w+|/Users/\w+", "local filesystem path"),
    (r"\bdata\d{2}[A-Za-z_]*\b|\bmc\d{2}_", "dataset / sample name"),
    (r"\bmS\d+\b", "signal mass-point tag"),
    (r"ANA-[A-Z]+-\d{4}-\d+", "internal analysis code"),
    (r"\b0\.\d{3,}\b", "precise result-like number (0.xxx)"),
    (r"\b\d+(\.\d+)?\s*(sd|sigma|se)\b", "significance-style quantity"),
    (r"\b(AUC|dCor|\|nc\|)\s*[=:]?\s*\d", "metric with a value"),
]


def bar(i: int, n: int, label: str, width: int = 28) -> None:
    done = int(width * i / n)
    sys.stdout.write(f"\r  [{'#' * done}{'.' * (width - done)}] {i}/{n}  {label:<24}")
    sys.stdout.flush()
    if i == n:
        sys.stdout.write("\n")


def load_projects() -> list[dict]:
    projs = []
    for d in sorted(p for p in PROJ.iterdir() if p.is_dir()):
        f = d / "project.json"
        if not f.exists():
            print(f"  ! {d.name}: no project.json, skipped")
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        data["_dir"] = d
        projs.append(data)
    return sorted(projs, key=lambda p: p.get("order", 999))


def validate(p: dict) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    pid = p.get("id", "?")
    for k in ("id", "name", "expansion", "status", "accent", "intro", "questions"):
        if k not in p:
            errs.append(f"{pid}: missing '{k}'")
    if p.get("id") != p["_dir"].name:
        errs.append(f"{pid}: id does not match folder '{p['_dir'].name}'")
    if p.get("status") not in STATUSES:
        errs.append(f"{pid}: status must be one of {sorted(STATUSES)}")
    for k in ("accent", "accent2"):
        if k in p and not re.fullmatch(r"#[0-9a-fA-F]{6}", p[k]):
            errs.append(f"{pid}: {k} must be #rrggbb")
    intro = p.get("intro", {})
    for k in INTRO_KEYS:
        s = intro.get(k, "").strip()
        if not s:
            errs.append(f"{pid}: intro.{k} is empty")
        elif len(re.sub(r"\[@[\w-]+\]", "", s).split()) > 60:
            warns.append(f"{pid}: intro.{k} is {len(s.split())} words (parsimony target <= 60)")
    q = p.get("questions", [])
    if not 2 <= len(q) <= 3:
        errs.append(f"{pid}: needs 2-3 questions, has {len(q)}")
    for i, s in enumerate(q, 1):
        if not s.strip().endswith("?"):
            warns.append(f"{pid}: question {i} does not end with '?'")
    if not (p["_dir"] / "source.png").exists():
        errs.append(f"{pid}: projects/{pid}/source.png missing")

    # timeline: dated entries in order, undated entries are future steps
    tl = p.get("timeline", [])
    if not tl:
        warns.append(f"{pid}: no timeline entries")
    last = ""
    for i, t in enumerate(tl, 1):
        d, st = t.get("date", ""), t.get("state")
        if st not in TL_STATES:
            errs.append(f"{pid}: timeline {i} state must be one of {sorted(TL_STATES)}")
        if d and not DATE_RE.match(d):
            errs.append(f"{pid}: timeline {i} date '{d}' must be YYYY, YYYY-MM or YYYY-MM-DD")
        if not t.get("label", "").strip():
            errs.append(f"{pid}: timeline {i} has no label")
        if d and d < last[: len(d)]:          # month-only dates compare at month precision
            warns.append(f"{pid}: timeline {i} is dated earlier than the entry before it")
        last = max(last, d)

    # literature
    lit = p.get("literature", [])
    if not lit:
        warns.append(f"{pid}: no literature entries")
    seen = set()
    for i, r in enumerate(lit, 1):
        for k in LIT_KEYS:
            if not str(r.get(k, "")).strip():
                errs.append(f"{pid}: literature {i} missing '{k}'")
        if not str(r.get("url", "")).startswith("https://"):
            errs.append(f"{pid}: literature {i} url must be https")
        key = re.sub(r"\W+", "", str(r.get("title", "")).lower())
        if key in seen:
            errs.append(f"{pid}: literature {i} duplicates an earlier title")
        seen.add(key)

    # inline citations: every [@key] must resolve to a literature entry
    lit_keys = [r.get("key") for r in lit if r.get("key")]
    if len(lit_keys) != len(set(lit_keys)):
        errs.append(f"{pid}: duplicate literature keys")
    cite_text = " ".join(list(intro.values()) + [c.get("summary", "") for c in p.get("components", [])]
                         + [it.get("detail", "") for c in p.get("components", []) for it in c.get("items", [])]
                         + [r.get("text", "") for r in p.get("results", [])])
    for k in sorted(set(re.findall(r"\[@([\w-]+)\]", cite_text)) - set(lit_keys)):
        errs.append(f"{pid}: citation [@{k}] has no literature entry with that key")

    for i, c in enumerate(p.get("components", []), 1):
        if not c.get("name") or not c.get("summary"):
            errs.append(f"{pid}: component {i} needs name and summary")
        if c.get("state") and c["state"] not in TL_STATES:
            errs.append(f"{pid}: component {i} state must be one of {sorted(TL_STATES)}")
    for i, l in enumerate(p.get("links", []), 1):
        if not (PROJ / str(l.get("project", "")) / "project.json").exists():
            errs.append(f"{pid}: link {i} points at unknown project '{l.get('project')}'")

    for i, o in enumerate(p.get("open", []), 1):
        if o.get("kind") not in OPEN_KINDS:
            errs.append(f"{pid}: open {i} kind must be one of {sorted(OPEN_KINDS)}")
    return errs, warns


def leak_scan(p: dict) -> list[str]:
    # Everything a visitor can read. Literature titles/venues are scanned too
    # (an internal note masquerading as a reference is exactly the risk); URLs are not.
    text = " ".join(
        [p.get("name", ""), p.get("expansion", ""), p.get("tagline", "")]
        + [f"{c.get('name', '')} {c.get('subtitle', '')} {c.get('summary', '')} "
           + " ".join(f"{it.get('label', '')} {it.get('detail', '')}" for it in c.get("items", []))
           for c in p.get("components", [])]
        + [f"{l.get('title', '')} {l.get('text', '')}" for l in p.get("links", [])]
        + [f"{r.get('title', '')} {r.get('text', '')}" for r in p.get("results", [])]
        + [p.get("intro", {}).get(k, "") for k in INTRO_KEYS]
        + p.get("questions", [])
        + [o.get("text", "") for o in p.get("open", [])]
        + [t.get("label", "") for t in p.get("timeline", [])]
        + [f"{r.get('title', '')} {r.get('venue', '')} {r.get('why', '')}" for r in p.get("literature", [])]
    )
    hits = []
    for pat, why in LEAK_PATTERNS:
        for m in re.finditer(pat, text):
            hits.append(f"{p['id']}: '{m.group(0)}'  -> {why}")
    return hits


def normalize(src: Path, size: tuple[int, int]) -> Image.Image:
    im = Image.open(src).convert("RGB")
    luma = im.convert("L").point(lambda v: 255 if v > LUMA_FLOOR else 0)
    box = luma.getbbox() or (0, 0, *im.size)
    art = im.crop(box)
    W, H = size
    avail_w, avail_h = W * (1 - 2 * MARGIN), H * (1 - 2 * MARGIN)
    s = min(avail_w / art.width, avail_h / art.height)
    art = art.resize((max(1, round(art.width * s)), max(1, round(art.height * s))), Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(art, ((W - art.width) // 2, (H - art.height) // 2))
    return canvas


def stamp_assets() -> None:
    """Rewrite ?v= on CSS/JS links in index.html to a content hash.

    Browsers cache stylesheets aggressively; a stale deck.css paired with a newer
    index.html breaks the layout. A changed file gets a new URL, so it is always refetched.
    """
    import hashlib
    page = ROOT / "index.html"
    html = page.read_text(encoding="utf-8")
    for rel in ("assets/css/deck.css", "assets/js/deck.js", "assets/js/registry.js"):
        h = hashlib.sha1((ROOT / rel).read_bytes()).hexdigest()[:10]
        html, n = re.subn(re.escape(rel) + r"(\?v=[\w-]*)?", f"{rel}?v={h}", html)
        if not n:
            print(f"  ! {rel} not referenced in index.html")
    page.write_text(html, encoding="utf-8")
    print("  stamped asset versions in index.html")


def public_record(p: dict) -> dict:
    rec = {k: v for k, v in p.items() if not k.startswith("_")}
    rec["logo"] = f"projects/{p['id']}/logo.webp"
    rec["thumb"] = f"projects/{p['id']}/thumb.webp"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true", help="validate + leak-scan only")
    args = ap.parse_args()

    t0 = time.time()
    print("== research-deck build ==")
    projs = load_projects()
    print(f"  found {len(projs)} projects")

    print("[1/3] validate")
    errs, warns = [], []
    for p in projs:
        e, w = validate(p)
        errs += e
        warns += w
    for w in warns:
        print(f"  warn  {w}")
    for e in errs:
        print(f"  ERROR {e}")
    print(f"  {len(errs)} errors, {len(warns)} warnings")

    print("[2/3] leak scan")
    leaks = [h for p in projs for h in leak_scan(p)]
    for h in leaks:
        print(f"  LEAK  {h}")
    print(f"  {len(leaks)} hits")

    if errs or leaks:
        print("FAILED -- fix the above before publishing.")
        return 1
    if args.check:
        print(f"check passed ({time.time() - t0:.1f}s)")
        return 0

    print("[3/3] normalize images + bundle")
    n = len(projs)
    for i, p in enumerate(projs, 1):
        bar(i - 1, n, p["id"])
        d = p["_dir"]
        normalize(d / "source.png", HERO).save(d / "logo.webp", "WEBP", quality=90, method=6)
        normalize(d / "source.png", THUMB).save(d / "thumb.webp", "WEBP", quality=86, method=6)
    bar(n, n, "done")

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([public_record(p) for p in projs], indent=1, ensure_ascii=False)
    REGISTRY.write_text(
        "// GENERATED by tools/build_deck.py -- edit projects/<id>/project.json instead.\n"
        f"window.DECK_PROJECTS = {payload};\n",
        encoding="utf-8",
    )
    stamp_assets()
    kb = sum((p["_dir"] / f).stat().st_size for p in projs for f in ("logo.webp", "thumb.webp")) / 1024
    print(f"  wrote {REGISTRY.relative_to(ROOT)}  |  images {kb:.0f} KB total")
    print(f"done ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
