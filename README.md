# research-deck

Public face for the project line: a static, no-build-step site with a **Gallery of Rogues** deck on top (a compact tile grid on the left, the selected project as a large tile on the right, and an info bar with the prev/next controls under the grid) and the selected project in the main panel below. Below 960 px the large tile is hidden, since the hero logo sits right under the gallery.

Live structure:

```
index.html                    page shell
glossary.html                 glossary page (extended definitions, filter, deep links #<term-key>)
todo.html                     to-do panel (items tagged by project and flag; filters; deep links)
assets/css/deck.css           TRON Ares dark theme; accent re-tints per project
assets/css/glossary.css       glossary page layout
assets/css/todo.css           to-do page additions (builds on glossary.css)
assets/js/deck.js             gallery + stage controller (routing, keys, swipe, term cards, math)
assets/js/glossary.js         glossary page controller
assets/js/todo.js             to-do page controller
assets/js/registry.js         GENERATED: projects, glossary and the site's last-revised date, bundled
assets/vendor/katex/          KaTeX 0.16.11 (MIT), vendored so math renders without a CDN
projects/<id>/
    project.json              content you edit
    source.png                original logo you replace
    logo.webp  thumb.webp     GENERATED: normalized 1600x1000 / 480x300
glossary/glossary.json        glossary terms you edit (one list for the whole site)
todo/todo.json                to-do items you edit (one list for the whole site)
tools/build_deck.py           normalize + validate + leak-scan + bundle
PUBLIC_SCOPE.md               what may and may not appear here
```

## Acronym titles

If a project name is one word, the page tries to spell it out of the expansion. For each letter it uses the next word that starts with it, or the next capital inside a word (e**X**periment), or failing that any unused word-initial (the T in Game-**T**heoretic). When every letter is found, the title is shown with periods (S.T.A.V.E) and those letters are highlighted in the expansion. Names with spaces (INFO THEORY, BEAM AGENT) stay plain. There's nothing to set by hand; to change which letters are highlighted, change the expansion's capitalization.

## Site icon

`assets/icons/source.png` is the master mark, a 1024×1024 square cropped to the ring. The favicons (`favicon.ico`, 16/32 px PNGs), `apple-touch-icon.png`, the 192/512 manifest icons, and the 96 px header mark are all cut from it. The 16–48 px sizes get a light unsharp mask so the ring and the A stay legible. To change the icon, replace `source.png` and regenerate the sizes.

## Page map

Under the hero logo there is a jump list for the current project: Overview, Questions, Open Items (if any), Progress, Literature, and one entry per literature category. Clicking a category also opens it. The jumps don't change the URL hash, because the hash selects the project. The entry you're reading is highlighted as you scroll.

## Run locally

Open `index.html` directly, or serve it:

```
python -m http.server 8000
```

Deep links: `index.html#gambit`. Keys: Left/Right to step, 1-9 to jump, 0 / - / = for the tenth to twelfth; projects past the twelfth are reached with the arrows or a click. Clicking the large tile scrolls to the project page. Swipe on mobile. The prev/next buttons play a short synthesized "boop" (Web Audio; no sound files).

## Edit a project

1. Edit `projects/<id>/project.json` (or replace `source.png`).
2. `python tools/build_deck.py`
3. Commit the generated `logo.webp`, `thumb.webp`, and `assets/js/registry.js` along with your edit.

`--check` validates and leak-scans without writing anything. CI runs the same check on every push.

### project.json

| field | rule |
|---|---|
| `id` | must match the folder name; used as the URL hash |
| `order` | position in the deck |
| `name`, `expansion` | wordmark and acronym expansion |
| `status` | `active` / `planning` / `paused` / `complete` |
| `accent`, `accent2` | `#rrggbb`; re-tints the page while selected |
| `code` | `internal` or `public` |
| `revised` | `YYYY-MM-DD`, the date the page was last revised; shown in the project kicker. Set it with `--revise <id>` |
| `site` | optional public website URL; lights the PUBLIC SITE pill and the tile's WEB light (green, blinking) |
| `private_repo` | optional `https://github.com/<owner>/<repo>`; lights the PRIVATE REPO pill and the tile's REPO light. Private repos return 404 to anyone not signed in with access, so the link only opens for the owner |
| `presentations` | optional https URL of the project's slide decks (usually its `ATLAS_presentations_<NAME>` GitHub Pages site); lights the PRESENTATIONS pill and the tile's DECK light |
| `intro.problem` | (1) topic sentence: the problem being addressed |
| `intro.value` | (2) what solving it adds to research |
| `intro.approach` | (3) how the problem is attacked |
| `intro.goals` | (4) intended goals and outcomes |
| `questions` | 2-3 questions the project is designed to answer |
| `tagline` | optional one-line label under the expansion |
| `components` | optional list of `{name, subtitle, state, summary, items:[{label, detail}]}`; renders as the PROGRAM section |
| `caveat` | optional `{date, text}`; amber banner at the top of the project panel, date shown as written |
| `results` | optional list of `{title, text}`; renders as CURRENT RESULTS, words only (no numbers on the public page) |
| `links` | optional list of `{project, title, text}`; a card that jumps to another project |
| `open` | optional list of `{kind, text}`; kind is `question`, `lesson` (learned, not yet applied) or `gap` |
| `timeline` | list of `{date, label, state}`; see below |
| `literature` | list of `{category, authors, year, title, venue, url, verified, why}`; grouped by `category` on the page |

The four intro fields render as one paragraph, in that order. The builder warns past 60 words per sentence.

### Updating progress

Each timeline entry is one row:

```json
{"date": "2026-10-16", "label": "What happened, in public-safe words", "state": "done"}
```

- `state`: `done` (filled node), `active` (pulsing node, shows NOW if undated), `next` (hollow node, shows NEXT).
- `date`: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. Leave it out for future steps.
- Keep dated entries in order; the builder warns if one goes backwards.
- To advance: flip the step you finished from `next` to `done`, give it a date, and add the next step at the bottom.

Labels are leak-scanned like everything else: no numbers, sample names or internal codes.

### Literature

To cite inline, give the reference a `key` and write `[@key]` in the intro or in any component summary or detail. Citations are numbered by first appearance, link to the entry in the literature list, and open its category when clicked. The build fails if a `[@key]` has no matching entry.

Every entry needs an https `url` to the paper's own page (arXiv abs, DOI or publisher). `verified` records how far the citation was checked: `full` if confirmed on the paper's own page, `abstract` if confirmed from metadata only. It does not say how deeply the paper was read. Titles and venues are leak-scanned too, so an internal note can't pass as a reference.

## Last revised

Every `project.json` carries `revised`, and `glossary/glossary.json` carries its own. The header shows **LAST REVISED**, the newest of all of them, computed at build time; each project page shows its own date next to its status.

After editing a page:

```
python tools/build_deck.py --revise dncn-qn     # stamps today's date, then builds
python tools/build_deck.py --revise glossary
```

The builder warns when a project has no `revised` and fails on a malformed or future date. The dates first set on 20 Nov 2026 are the last commit that touched each `project.json`.

## Glossary

`glossary/glossary.json` holds one list of terms for the whole site; `glossary.html` shows them grouped by category, with a filter and a link per entry (`glossary.html#<key>`).

```json
{"key": "soft-count", "term": "Soft count", "category": "Closure terms: ingredients",
 "inline": "soft count", "sort": "soft count",
 "aka": ["$N_X$"], "short": "One or two sentences.", "long": ["Paragraph.", "Paragraph."],
 "see": ["hard-count"], "projects": ["baseline"],
 "refs": [{"title": "...", "venue": "...", "url": "https://..."}]}
```

| field | rule |
|---|---|
| `key` | lowercase words joined by `-`; the anchor and the link target |
| `term` | heading shown in the glossary; may hold math |
| `category` | groups entries; categories appear in the order they first occur in the file |
| `short` | the definition shown on a project page's term card |
| `long` | optional paragraphs, shown only in the glossary |
| `inline` | optional: the words a bare `[[key]]` shows in running text. Default: `term`, with the first letter lowered when it is the only capital |
| `sort` | optional sort name (for terms that start with math) |
| `aka`, `see` | other names; related keys (must exist) |
| `projects` | optional extra project ids for USED IN; projects that link the term are added automatically |
| `refs` | optional sources, https only |

**Linking a term.** In any intro, component summary or detail, result or open item, write `[[key]]` or `[[key|shown words]]`. It renders with a dashed underline; clicking opens a card with the short definition and a link to the full entry. Glossary entries can link each other the same way. The build fails on a link to a key that doesn't exist.

**Math.** Write `$...$` inline and `$$...$$` for a display line, in project text and in the glossary. KaTeX renders it; the build fails on an unbalanced `$`.

The glossary is leak-scanned with the same patterns as project text and falls under the same public scope: method definitions, no internal numbers.

## To-do panel

`todo/todo.json` holds one list for the whole site. It is shown on `todo.html` (TO DO button in the header, with the open count) and, per project, as a TO DO section on each project page listing that project's unfinished items.

```json
{
  "revised": "2026-11-23",
  "flags": [{ "key": "analysis", "label": "ANALYSIS", "color": "#ffc83a" }],
  "items": [{
    "id": "T007", "status": "open", "added": "2026-11-23",
    "projects": ["abcd-plane-health", "info-theory"], "flags": ["analysis"], "after": ["T006"],
    "text": "One line; $math$ allowed", "detail": "Optional longer note"
  }]
}
```

| field | rule |
|---|---|
| `id` | `T` + three digits, unique; never reuse an id |
| `status` | `active`, `open`, `blocked` or `done`; a done item needs a `done` date |
| `projects` | project ids it applies to; empty means site-wide |
| `flags` | keys from `flags[]` (each flag has a label and a `#rrggbb` colour) |
| `after` | ids of items this one waits on |

Deep links: `todo.html#T007` (one item), `todo.html#project=<id>`, `todo.html#flag=<key>`, `todo.html#status=open`; filters combine with `&`. After editing, `python tools/build_deck.py --revise todo`. To-do text is leak-scanned like project text: **this list is public**, so keep internal numbers out of it.

## Add a project

Create `projects/<new-id>/` with `project.json` and `source.png`, then build. The logo must sit on a black background: normalization trims to visible content and pads on `#000`, it never stretches or crops the artwork.

## Publish

GitHub Pages from the repo root (Settings -> Pages -> Deploy from branch -> `main` / root). Nothing to build on the server; every generated file is committed.

## License

- Code (`assets/js`, `assets/css`, `tools`, `index.html`): Apache-2.0, see `LICENSE`.
- Project text (`projects/*/project.json`): CC BY 4.0.
- Logos (`projects/*/source.png`, `logo.webp`, `thumb.webp`): all rights reserved; not covered by either license above.
