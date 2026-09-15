# docs/archive — frozen copies of superseded files

Verbatim snapshots of files that were replaced wholesale, kept so the previous
state is findable without digging through `git log`. Nothing here is live and
nothing here is generated: no workflow reads this directory, and no script
writes to it.

| File | What it is |
|---|---|
| `index-2026-09-pre-redesign.html` | The whole single-file frontend as it stood immediately **before the 2026-09 major UI overhaul** — commit `2ee3c55`, the last state of the dark "Neo-Kinpaku" design. |

## About `index-2026-09-pre-redesign.html`

This is the last version of `index.html` before the redesign that introduced the
light editorial look, the four-entry primary navigation (Charts / Map / Rankings
/ Tools), the landing-page hero chart and the Source Serif 4 + Public Sans type
pairing.

It is **byte-identical** to the old `index.html`, deliberately. It is a
historical record, so it was not cleaned up, re-themed or otherwise touched —
including its `<base href="https://leraffl.github.io/LeRaffl-Gallery/">`, which
means opening this file locally still pulls data and images from the live site.

Two consequences worth knowing:

- GitHub Pages serves every path in this repository, so this file is reachable
  at `/LeRaffl-Gallery/docs/archive/index-2026-09-pre-redesign.html`. Nothing
  links to it, but it is not private.
- It carries the pre-fix `getT0Years()`, so every absolute date it renders
  (Thresholds, Time Interval, World Map year mode, gallery status pills) is one
  year too late. See the PR that introduced the redesign, and the
  `CALENDAR-YEAR FIX (2026-06)` comment at `inv_x_years()` in the current
  `index.html`, for why. Do not quote numbers off this page.

As always, `data/<Country>.csv` is the single source of truth — an archived
frontend least of all.
