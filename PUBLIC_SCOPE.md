# Public scope

This repository is public. It describes projects; it does not report them.

## Allowed

- What each project is, why it matters, how it is approached, what it aims to deliver
- The questions it is designed to answer
- Method names and general techniques
- Links to results that are already public (papers, public notes, conference proceedings)

## Not allowed

- Numbers from internal work: scores, closure values, significances, event counts, cut values
- Plots, tables, or figures from internal analyses
- Sample, dataset, or internal analysis identifiers
- Internal hosts, filesystem paths, or repository links
- Code from the internal repositories, unless separately cleared

## Enforcement

`tools/build_deck.py` scans all project text for the patterns above and refuses to build on a hit. The same scan runs in CI (`.github/workflows/check.yml`). The pattern list lives in `LEAK_PATTERNS` and should grow whenever something new needs blocking.

A clean scan is necessary, not sufficient: the scan catches identifiers and numbers, not substance. Scope beyond method descriptions is cleared with the research advisor before it is published here.
