#!/usr/bin/env python3
"""
build_deck.py  --  normalize project logos, validate content, scan for leaks,
                   and bundle everything into assets/js/registry.js.

Each project lives in projects/<id>/ :
    source.png     original logo (any size; black background)   <- you edit
    project.json   content                                       <- you edit
                   sub_label  optional: word used for this project's sub-projects (e.g. "CHAPTER"); default SUB-PROJECT
                   kind       optional: "project" (default) or "todo" -- a tile whose page is the to-do list;
                              it needs only id, name, expansion, status, accent and source.png
                   components[] = programs / sub-projects; optional per component:
                     codename  sub-project name shown as the title (e.g. "SIGNAL LINE")
                     synopsis  one line for the sub-project strip under the intro
                     slug      anchor override; default is the codename (or name) -> #<id>/<slug>
                     page      optional sub-page, shown at #<id>/<slug> in place of the project body:
                               lede (required), figure {svg, caption} (svg file in projects/<id>/),
                               sections [{heading, text, items[{label, detail}]}], outputs [{label, detail}],
                               repo_path (folder inside the private repo), timeline [], open [],
                               downloads [{label, path, detail}] (paths inside repo_path; links to the private repo)
    logo.webp      1600x1000 normalized hero                     <- generated
    thumb.webp      480x300  normalized gallery card             <- generated

Normalization never stretches or crops artwork: the logo is trimmed to its
visible content, given a uniform margin, and centred on a pure-black 16:10
canvas. All sources are on #000, so the padding is invisible.

The glossary lives in glossary/glossary.json (one list of terms for the whole site).
The to-do panel lives in todo/todo.json: items with an id (T001...), a status (open, active, blocked, done),
the projects they apply to, and flags; shown on todo.html and, per project, on each project page.
Project text links a term with [[key]] or [[key|shown text]]; math is $...$ (KaTeX).

Usage:
    python tools/build_deck.py                  # build (fails on errors)
    python tools/build_deck.py --check          # validate + leak-scan only, write nothing
    python tools/build_deck.py --revise dncn-qn # stamp today's date as that project's 'revised', then build
    python tools/build_deck.py --revise glossary
    python tools/build_deck.py --revise todo

Requires: Pillow
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT / "projects"
REGISTRY = ROOT / "assets" / "js" / "registry.js"
GLOSSARY = ROOT / "glossary" / "glossary.json"
TODO = ROOT / "todo" / "todo.json"

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
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")          # 'revised' must be a full date
TERM_RE = re.compile(r"\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]")  # [[key]] or [[key|shown text]]
KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CODENAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{0,23}$")   # sub-project names: caps, <= 24 chars
SYNOPSIS_WORDS = 22                                       # one line in the sub-project strip


def comp_slug(c: dict) -> str:
    """Anchor for a program / sub-project: #<project>/<slug>. Explicit 'slug' wins, else codename, else name."""
    src = c.get("slug") or c.get("codename") or c.get("name", "")
    return re.sub(r"[^a-z0-9]+", "-", src.lower()).strip("-")

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


KINDS = {"project", "todo"}     # kind "todo": a gallery tile whose page is the to-do list (todo/todo.json)


def validate_todo_tile(p: dict) -> tuple[list[str], list[str]]:
    """The #TO_DO tile has a logo and a header but no project content; its body comes from todo/todo.json."""
    errs = []
    pid = p.get("id", "?")
    for k in ("id", "name", "expansion", "status", "accent"):
        if k not in p:
            errs.append(f"{pid}: missing '{k}'")
    if p.get("id") != p["_dir"].name:
        errs.append(f"{pid}: id does not match folder '{p['_dir'].name}'")
    if p.get("status") not in STATUSES:
        errs.append(f"{pid}: status must be one of {sorted(STATUSES)}")
    if not (p["_dir"] / "source.png").exists():
        errs.append(f"{pid}: projects/{pid}/source.png missing")
    for k in ("intro", "questions", "components", "timeline", "literature", "open", "results", "links"):
        if k in p:
            errs.append(f"{pid}: a to-do tile takes no '{k}'; edit todo/todo.json instead")
    return errs, []


def validate(p: dict) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    pid = p.get("id", "?")
    if p.get("kind", "project") not in KINDS:
        return [f"{pid}: kind must be one of {sorted(KINDS)}"], warns
    if p.get("kind") == "todo":
        return validate_todo_tile(p)
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
    if "link" in p:
        errs.append(f"{pid}: 'link' was renamed 'site' (public website)")
    if "sub_label" in p and not re.fullmatch(r"[A-Z][A-Z -]{0,15}", str(p["sub_label"])):
        errs.append(f"{pid}: sub_label must be capitals/space/hyphen, <= 16 chars")
    if p.get("site") and not str(p["site"]).startswith("https://"):
        errs.append(f"{pid}: site must be an https URL")
    if p.get("private_repo") and not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", str(p["private_repo"])):
        errs.append(f"{pid}: private_repo must be https://github.com/<owner>/<repo>")
    if p.get("presentations") and not str(p["presentations"]).startswith("https://"):
        errs.append(f"{pid}: presentations must be an https URL")
    rv = p.get("revised")
    if not rv:
        warns.append(f"{pid}: no 'revised' date (run --revise {pid} after editing)")
    elif not DAY_RE.match(str(rv)):
        errs.append(f"{pid}: revised '{rv}' must be YYYY-MM-DD")
    elif str(rv) > dt.date.today().isoformat():
        errs.append(f"{pid}: revised '{rv}' is in the future")
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

    slugs = set()
    for i, c in enumerate(p.get("components", []), 1):
        if not c.get("name") or not c.get("summary"):
            errs.append(f"{pid}: component {i} needs name and summary")
        if c.get("state") and c["state"] not in TL_STATES:
            errs.append(f"{pid}: component {i} state must be one of {sorted(TL_STATES)}")
        if "codename" in c and not CODENAME_RE.match(str(c["codename"])):
            errs.append(f"{pid}: component {i} codename '{c['codename']}' must be capitals/digits/space/hyphen, <= 24 chars")
        if c.get("slug") and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", c["slug"]):
            errs.append(f"{pid}: component {i} slug must be lowercase words joined by '-'")
        sl = comp_slug(c)
        if not sl:
            errs.append(f"{pid}: component {i} has no usable anchor (give it a codename or slug)")
        elif sl in slugs:
            errs.append(f"{pid}: component {i} anchor '#{pid}/{sl}' duplicates an earlier component")
        slugs.add(sl)
        syn = str(c.get("synopsis", "")).strip()
        if syn and len(syn.split()) > SYNOPSIS_WORDS:
            warns.append(f"{pid}: component {i} synopsis is {len(syn.split())} words (target <= {SYNOPSIS_WORDS})")
        if "page" in c:
            e, w = validate_page(p, c, i)
            errs += e
            warns += w
    named = [c for c in p.get("components", []) if c.get("codename")]
    if named and len(named) != len(p.get("components", [])):
        warns.append(f"{pid}: {len(named)} of {len(p['components'])} components have a codename (name all or none)")
    for i, l in enumerate(p.get("links", []), 1):
        if not (PROJ / str(l.get("project", "")) / "project.json").exists():
            errs.append(f"{pid}: link {i} points at unknown project '{l.get('project')}'")

    for i, o in enumerate(p.get("open", []), 1):
        if o.get("kind") not in OPEN_KINDS:
            errs.append(f"{pid}: open {i} kind must be one of {sorted(OPEN_KINDS)}")
    return errs, warns


SVG_BAD = re.compile(r"<script|\son\w+\s*=|javascript:|<foreignObject|xlink:href\s*=\s*[\"']https?:", re.I)


def validate_page(p: dict, c: dict, i: int) -> tuple[list[str], list[str]]:
    """A component's sub-page (#<id>/<slug>)."""
    errs, warns = [], []
    pid, pg = p.get("id", "?"), c.get("page")
    tag = f"{pid}: component {i} page"
    if not isinstance(pg, dict):
        return [f"{tag} must be an object"], warns
    if not str(pg.get("lede", "")).strip():
        errs.append(f"{tag} needs a 'lede'")
    elif len(pg["lede"].split()) > 90:
        warns.append(f"{tag} lede is {len(pg['lede'].split())} words (target <= 90)")
    fig = pg.get("figure")
    if fig:
        svg = p["_dir"] / str(fig.get("svg", ""))
        if not fig.get("svg") or not svg.is_file():
            errs.append(f"{tag} figure svg '{fig.get('svg')}' not found in projects/{pid}/")
        elif SVG_BAD.search(svg.read_text(encoding="utf-8")):
            errs.append(f"{tag} figure svg holds script, event handlers or external links")
    secs = pg.get("sections", [])
    if not secs:
        errs.append(f"{tag} needs at least one section")
    for j, sec in enumerate(secs, 1):
        if not str(sec.get("heading", "")).strip():
            errs.append(f"{tag} section {j} has no heading")
        if not (str(sec.get("text", "")).strip() or sec.get("items")):
            errs.append(f"{tag} section {j} has neither text nor items")
    for j, t in enumerate(pg.get("timeline", []), 1):
        if t.get("state") not in TL_STATES or not t.get("label"):
            errs.append(f"{tag} timeline {j} needs a label and a state in {sorted(TL_STATES)}")
        if t.get("date") and not DATE_RE.match(t["date"]):
            errs.append(f"{tag} timeline {j} date must be YYYY, YYYY-MM or YYYY-MM-DD")
    for j, o in enumerate(pg.get("open", []), 1):
        if o.get("kind") not in OPEN_KINDS:
            errs.append(f"{tag} open {j} kind must be one of {sorted(OPEN_KINDS)}")
    for j, d in enumerate(pg.get("downloads", []), 1):
        if not d.get("label") or not d.get("path"):
            errs.append(f"{tag} download {j} needs a label and a path")
        elif not re.fullmatch(r"[\w.-]+(/[\w.-]+)*", str(d["path"])):
            errs.append(f"{tag} download {j} path must be relative to repo_path")
    if pg.get("downloads") and not pg.get("repo_path"):
        errs.append(f"{tag} has downloads but no repo_path")
    if pg.get("repo_path"):
        if not p.get("private_repo"):
            errs.append(f"{tag} has repo_path but the project has no private_repo")
        if not re.fullmatch(r"[\w.-]+(/[\w.-]+)*", str(pg["repo_path"])):
            errs.append(f"{tag} repo_path must be a relative folder path")
    return errs, warns


def page_text(p: dict, c: dict) -> str:
    """Everything a visitor can read on a sub-page, the figure's text included."""
    pg = c.get("page") or {}
    parts = [pg.get("lede", ""), (pg.get("figure") or {}).get("caption", "")]
    for sec in pg.get("sections", []):
        parts += [sec.get("heading", ""), sec.get("text", "")]
        parts += [f"{it.get('label', '')} {it.get('detail', '')}" for it in sec.get("items", [])]
    parts += [f"{o.get('label', '')} {o.get('detail', '')}" for o in pg.get("outputs", [])]
    parts += [t.get("label", "") for t in pg.get("timeline", [])] + [o.get("text", "") for o in pg.get("open", [])]
    parts += [f"{d.get('label', '')} {d.get('detail', '')}" for d in pg.get("downloads", [])]
    fig = pg.get("figure") or {}
    svg = p["_dir"] / str(fig.get("svg", "")) if fig.get("svg") else None
    if svg and svg.is_file():
        parts.append(re.sub(r"<[^>]+>", " ", svg.read_text(encoding="utf-8")))
    return " ".join(parts)


def project_text(p: dict) -> str:
    # Everything a visitor can read. Literature titles/venues are included
    # (an internal note masquerading as a reference is exactly the risk); URLs are not.
    return " ".join(
        [p.get("name", ""), p.get("expansion", ""), p.get("tagline", ""), (p.get("caveat") or {}).get("text", "")]
        + [f"{c.get('codename', '')} {c.get('name', '')} {c.get('subtitle', '')} {c.get('synopsis', '')} {c.get('summary', '')} "
           + " ".join(f"{it.get('label', '')} {it.get('detail', '')}" for it in c.get("items", []))
           for c in p.get("components", [])]
        + [f"{l.get('title', '')} {l.get('text', '')}" for l in p.get("links", [])]
        + [f"{r.get('title', '')} {r.get('text', '')}" for r in p.get("results", [])]
        + [p.get("intro", {}).get(k, "") for k in INTRO_KEYS]
        + p.get("questions", [])
        + [o.get("text", "") for o in p.get("open", [])]
        + [t.get("label", "") for t in p.get("timeline", [])]
        + [f"{r.get('title', '')} {r.get('venue', '')} {r.get('why', '')}" for r in p.get("literature", [])]
        + [page_text(p, c) for c in p.get("components", []) if c.get("page")]
    )


def leak_scan(p: dict) -> list[str]:
    text = project_text(p)
    hits = []
    for pat, why in LEAK_PATTERNS:
        for m in re.finditer(pat, text):
            hits.append(f"{p['id']}: '{m.group(0)}'  -> {why}")
    return hits


# --- glossary ----------------------------------------------------------------
GLOSS_KEYS = ("key", "term", "category", "short")


def load_glossary() -> dict:
    if not GLOSSARY.exists():
        return {"revised": "", "terms": []}
    return json.loads(GLOSSARY.read_text(encoding="utf-8"))


def gloss_text(t: dict) -> str:
    refs = " ".join(f"{r.get('title', '')} {r.get('venue', '')}" for r in t.get("refs", []))
    return " ".join([t.get("term", ""), " ".join(t.get("aka", [])), t.get("category", ""), t.get("short", ""),
                     " ".join(t.get("long", [])), refs])


def validate_glossary(g: dict, projs: list[dict]) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    terms = g.get("terms", [])
    rv = g.get("revised", "")
    if terms and not DAY_RE.match(str(rv)):
        errs.append("glossary: 'revised' must be YYYY-MM-DD (run --revise glossary)")
    keys = [t.get("key") for t in terms]
    if len(keys) != len(set(keys)):
        errs.append("glossary: duplicate keys")
    known = set(keys)
    pids = {p["id"] for p in projs}
    for i, t in enumerate(terms, 1):
        k = t.get("key", f"#{i}")
        for f in GLOSS_KEYS:
            if not str(t.get(f, "")).strip():
                errs.append(f"glossary {k}: missing '{f}'")
        if not KEY_RE.match(str(t.get("key", ""))):
            errs.append(f"glossary {k}: key must be lowercase words joined by '-'")
        if "$" in t.get("short", "") and len(t["short"]) > 400:
            warns.append(f"glossary {k}: short definition is long; move detail into 'long'")
        if not isinstance(t.get("long", []), list):
            errs.append(f"glossary {k}: 'long' must be a list of paragraphs")
        for s in t.get("see", []):
            if s not in known:
                errs.append(f"glossary {k}: see-also '{s}' is not a glossary key")
        for pid in t.get("projects", []):
            if pid not in pids:
                errs.append(f"glossary {k}: project '{pid}' does not exist")
        for r in t.get("refs", []):
            if not str(r.get("url", "")).startswith("https://") or not r.get("title"):
                errs.append(f"glossary {k}: each ref needs a title and an https url")
        body = " ".join([t.get("short", "")] + t.get("long", []))
        for m in TERM_RE.finditer(body):
            if m.group(1) not in known:
                errs.append(f"glossary {k}: link [[{m.group(1)}]] is not a glossary key")
        if body.count("$") % 2:
            errs.append(f"glossary {k}: unbalanced $ (math delimiters)")
    # every [[key]] in project text must resolve
    for p in projs:
        for m in TERM_RE.finditer(project_text(p)):
            if m.group(1) not in known:
                errs.append(f"{p['id']}: term link [[{m.group(1)}]] is not a glossary key")
        if project_text(p).count("$") % 2:
            errs.append(f"{p['id']}: unbalanced $ (math delimiters)")
    return errs, warns


def gloss_scan(g: dict) -> list[str]:
    hits = []
    for t in g.get("terms", []):
        text = gloss_text(t)
        for pat, why in LEAK_PATTERNS:
            for m in re.finditer(pat, text):
                hits.append(f"glossary {t.get('key')}: '{m.group(0)}'  -> {why}")
    return hits


def public_glossary(g: dict, projs: list[dict]) -> dict:
    """Terms sorted by name, each with 'used_in': explicit projects plus every project whose text links it."""
    terms = []
    for t in sorted(g.get("terms", []), key=lambda t: (t.get("sort") or t["term"]).lower()):
        used = list(t.get("projects", []))
        for p in projs:
            if p["id"] not in used and re.search(r"\[\[" + re.escape(t["key"]) + r"(\||\]\])", project_text(p)):
                used.append(p["id"])
        terms.append(dict(t, used_in=sorted(used, key=lambda pid: next(q.get("order", 999) for q in projs if q["id"] == pid))))
    cats = []
    for t in g.get("terms", []):                  # categories in the order they first appear in glossary.json
        if t.get("category") not in cats:
            cats.append(t.get("category"))
    return {"revised": g.get("revised", ""), "categories": cats, "terms": terms}


# --- to-do panel ---------------------------------------------------------------
TODO_STATUSES = ("active", "open", "blocked", "done")      # display order
TODO_ID_RE = re.compile(r"^T\d{3}$")


def load_todo() -> dict:
    if not TODO.exists():
        return {"revised": "", "flags": [], "items": []}
    return json.loads(TODO.read_text(encoding="utf-8"))


def validate_todo(t: dict, projs: list[dict]) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    rv = t.get("revised")
    if t.get("items") and not (rv and DAY_RE.match(str(rv))):
        errs.append("todo: 'revised' must be YYYY-MM-DD (run --revise todo)")
    elif rv and str(rv) > dt.date.today().isoformat():
        errs.append(f"todo: revised '{rv}' is in the future")
    flags = t.get("flags", [])
    fkeys = [f.get("key") for f in flags]
    if len(fkeys) != len(set(fkeys)):
        errs.append("todo: duplicate flag keys")
    for f in flags:
        if not KEY_RE.match(str(f.get("key", ""))) or not str(f.get("label", "")).strip():
            errs.append(f"todo flag {f.get('key')}: needs a lowercase key and a label")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(f.get("color", ""))):
            errs.append(f"todo flag {f.get('key')}: color must be #rrggbb")
    pids = {p["id"] for p in projs if p.get("kind", "project") == "project"}
    if sum(p.get("kind") == "todo" for p in projs) > 1:
        errs.append("todo: more than one project has kind 'todo'")
    items = t.get("items", [])
    ids = [it.get("id") for it in items]
    if len(ids) != len(set(ids)):
        errs.append("todo: duplicate item ids")
    for it in items:
        k = it.get("id", "?")
        if not TODO_ID_RE.match(str(k)):
            errs.append(f"todo {k}: id must look like T001")
        if not str(it.get("text", "")).strip():
            errs.append(f"todo {k}: empty text")
        if it.get("status") not in TODO_STATUSES:
            errs.append(f"todo {k}: status must be one of {list(TODO_STATUSES)}")
        for pid in it.get("projects", []):
            if pid not in pids:
                errs.append(f"todo {k}: project '{pid}' does not exist")
        for fk in it.get("flags", []):
            if fk not in fkeys:
                errs.append(f"todo {k}: flag '{fk}' is not defined in flags[]")
        for a in it.get("after", []):
            if a not in ids:
                errs.append(f"todo {k}: after '{a}' is not an item id")
        if not DAY_RE.match(str(it.get("added", ""))):
            errs.append(f"todo {k}: 'added' must be YYYY-MM-DD")
        if it.get("status") == "done" and not DAY_RE.match(str(it.get("done", ""))):
            errs.append(f"todo {k}: a done item needs a 'done' date (YYYY-MM-DD)")
        if it.get("status") != "done" and it.get("done"):
            errs.append(f"todo {k}: has a 'done' date but status is {it.get('status')}")
        for fld in ("text", "detail"):
            if str(it.get(fld, "")).count("$") % 2:
                errs.append(f"todo {k}: unbalanced $ in {fld}")
        if not it.get("projects"):
            warns.append(f"todo {k}: no project tag (shown as site-wide)")
    return errs, warns


def todo_scan(t: dict) -> list[str]:
    hits = []
    for it in t.get("items", []):
        text = f"{it.get('text', '')} {it.get('detail', '')}"
        for pat, why in LEAK_PATTERNS:
            for m in re.finditer(pat, text):
                hits.append(f"todo {it.get('id')}: '{m.group(0)}'  -> {why}")
    return hits


def revise(target: str) -> int:
    today = dt.date.today().isoformat()
    f = {"glossary": GLOSSARY, "todo": TODO}.get(target, PROJ / target / "project.json")
    if not f.exists():
        print(f"  ! no such project, glossary or todo: {target}")
        return 1
    data = json.loads(f.read_text(encoding="utf-8"))
    data["revised"] = today
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {target}: revised -> {today}")
    return 0


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
    assets = {"index.html": ("assets/css/deck.css", "assets/js/deck.js", "assets/js/registry.js"),
              "glossary.html": ("assets/css/deck.css", "assets/css/glossary.css", "assets/js/registry.js",
                                "assets/js/glossary.js"),
              "todo.html": ("assets/css/deck.css", "assets/css/glossary.css", "assets/css/todo.css", "assets/js/registry.js", "assets/js/todo.js")}
    for name, rels in assets.items():
        page = ROOT / name
        if not page.exists():
            print(f"  ! {name} missing")
            continue
        html = page.read_text(encoding="utf-8")
        for rel in rels:
            h = hashlib.sha1((ROOT / rel).read_bytes()).hexdigest()[:10]
            html, n = re.subn(re.escape(rel) + r"(\?v=[\w-]*)?", f"{rel}?v={h}", html)
            if not n:
                print(f"  ! {rel} not referenced in {name}")
        page.write_text(html, encoding="utf-8")
    print("  stamped asset versions in index.html, glossary.html and todo.html")


def public_record(p: dict) -> dict:
    rec = {k: v for k, v in p.items() if not k.startswith("_")}
    rec["logo"] = f"projects/{p['id']}/logo.webp"
    rec["thumb"] = f"projects/{p['id']}/thumb.webp"
    rec["components"] = [public_component(p, c) for c in p.get("components", [])]
    return rec


def public_component(p: dict, c: dict) -> dict:
    out = dict(c, slug=comp_slug(c))
    pg = c.get("page")
    if pg:
        pg = dict(pg)
        fig = pg.get("figure")
        if fig and fig.get("svg"):           # inline the figure so the page works from file:// too
            markup = (p["_dir"] / fig["svg"]).read_text(encoding="utf-8")
            markup = re.sub(r"<\?xml[^>]*>\s*", "", markup)
            pg["figure"] = dict(fig, markup=markup)
        if pg.get("repo_path") and p.get("private_repo"):
            pg["repo_url"] = f"{p['private_repo']}/tree/main/{pg['repo_path']}"
            pg["downloads"] = [dict(d, url=f"{p['private_repo']}/raw/main/{pg['repo_path']}/{d['path']}")
                               for d in pg.get("downloads", [])]
        out["page"] = pg
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true", help="validate + leak-scan only")
    ap.add_argument("--revise", metavar="ID", help="set 'revised' to today for project ID (or 'glossary'), then build")
    args = ap.parse_args()
    if args.revise and revise(args.revise):
        return 1

    t0 = time.time()
    print("== research-deck build ==")
    projs = load_projects()
    gloss = load_glossary()
    todo = load_todo()
    print(f"  found {len(projs)} projects, {len(gloss.get('terms', []))} glossary terms, {len(todo.get('items', []))} to-do items")

    print("[1/3] validate")
    errs, warns = [], []
    for p in projs:
        e, w = validate(p)
        errs += e
        warns += w
    e, w = validate_glossary(gloss, projs)
    errs += e
    warns += w
    e, w = validate_todo(todo, projs)
    errs += e
    warns += w
    for w in warns:
        print(f"  warn  {w}")
    for e in errs:
        print(f"  ERROR {e}")
    print(f"  {len(errs)} errors, {len(warns)} warnings")

    print("[2/3] leak scan")
    leaks = [h for p in projs for h in leak_scan(p)] + gloss_scan(gloss) + todo_scan(todo)
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
    pub_gloss = public_glossary(gloss, projs)
    # site-wide 'last revised' = newest of any project's, the glossary's or the to-do panel's revised date
    dates = [str(p["revised"]) for p in projs if p.get("revised")] + ([pub_gloss["revised"]] if pub_gloss["revised"] else [])
    dates += [str(todo["revised"])] if todo.get("revised") else []
    meta = {"revised": max(dates) if dates else ""}
    REGISTRY.write_text(
        "// GENERATED by tools/build_deck.py -- edit projects/<id>/project.json, glossary/glossary.json or todo/todo.json instead.\n"
        f"window.DECK_META = {json.dumps(meta)};\n"
        f"window.DECK_PROJECTS = {payload};\n"
        f"window.DECK_GLOSSARY = {json.dumps(pub_gloss, indent=1, ensure_ascii=False)};\n"
        f"window.DECK_TODO = {json.dumps(todo, indent=1, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    n_open = sum(1 for it in todo.get("items", []) if it.get("status") != "done")
    print(f"  site revised {meta['revised'] or '(none)'}  |  glossary {len(pub_gloss['terms'])} terms  |  to-do {n_open} open")
    stamp_assets()
    kb = sum((p["_dir"] / f).stat().st_size for p in projs for f in ("logo.webp", "thumb.webp")) / 1024
    print(f"  wrote {REGISTRY.relative_to(ROOT)}  |  images {kb:.0f} KB total")
    print(f"done ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
