# research-deck

Public face for the project line: a static, no-build-step site with a **Gallery of Rogues** strip on top and the selected project in the main panel below.

Live structure:

```
index.html                    page shell
assets/css/deck.css           TRON Ares dark theme; accent re-tints per project
assets/js/deck.js             gallery + stage controller (routing, keys, swipe)
assets/js/registry.js         GENERATED: all project data bundled for the page
projects/<id>/
    project.json              content you edit
    source.png                original logo you replace
    logo.webp  thumb.webp     GENERATED: normalized 1600x1000 / 480x300
tools/build_deck.py           normalize + validate + leak-scan + bundle
PUBLIC_SCOPE.md               what may and may not appear here
```

## Run locally

Open `index.html` directly, or serve it:

```
python -m http.server 8000
```

Deep links: `index.html#gambit`. Keys: Left/Right to step, 1-9 to jump. Swipe on mobile.

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
| `link` | optional URL shown under the questions |
| `intro.problem` | (1) topic sentence: the problem being addressed |
| `intro.value` | (2) what solving it adds to research |
| `intro.approach` | (3) how the problem is attacked |
| `intro.goals` | (4) intended goals and outcomes |
| `questions` | 2-3 questions the project is designed to answer |

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

Every entry needs an https `url` to the paper's own page (arXiv abs, DOI or publisher). `verified` records how far the citation was checked: `full` if confirmed on the paper's own page, `abstract` if confirmed from metadata only. It does not say how deeply the paper was read. Titles and venues are leak-scanned too, so an internal note can't pass as a reference.

## Add a project

Create `projects/<new-id>/` with `project.json` and `source.png`, then build. The logo must sit on a black background: normalization trims to visible content and pads on `#000`, it never stretches or crops the artwork.

## Publish

GitHub Pages from the repo root (Settings -> Pages -> Deploy from branch -> `main` / root). Nothing to build on the server; every generated file is committed.

## License

- Code (`assets/js`, `assets/css`, `tools`, `index.html`): Apache-2.0, see `LICENSE`.
- Project text (`projects/*/project.json`): CC BY 4.0.
- Logos (`projects/*/source.png`, `logo.webp`, `thumb.webp`): all rights reserved; not covered by either license above.
