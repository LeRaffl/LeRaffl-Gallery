#!/usr/bin/env python3
"""Extract the design tokens from index.html into assets/theme.css.

Usage
-----
    python scripts/build_theme.py
    python scripts/build_theme.py --check        # verify, don't write
    python scripts/build_theme.py --index index.html --out assets/theme.css

Why this exists (#221)
----------------------
`index.html` moved to a light editorial theme in the 2026-09 redesign (#218).
The other two published surfaces did not: `sources/*.html` carried its own dark
palette and `schedule*.html` a third, older one. "Data sources" is linked
straight from the Tools nav, so a visitor went from the new design to the old
one in a single click.

Hand-porting the palette into each generator would have left three copies to
drift. Instead **`index.html` stays the single source of truth** and this
script lifts its `:root` block out into a stylesheet the generated pages link.
The generators span two languages (`scripts/build_source_pages.py` in Python,
`R/render_schedule.R` in R), so a shared *file* is the only thing both can use;
a shared Python module would not reach the R side.

Consequences worth knowing:

- `assets/theme.css` is **generated — never hand-edit it.** Change a colour in
  `index.html`'s `:root` block and re-run this script.
- Extraction is strict. If the `:root` block or the font `<link>` cannot be
  found, this script **fails loudly** rather than emitting a stylesheet that
  silently lost half the palette. A refactor of `index.html`'s head that breaks
  the markers below should break the build, not the site.
- `--check` re-derives the CSS and compares it to the file on disk, so CI can
  prove the committed stylesheet matches `index.html` without writing.

Dark mode
---------
`index.html` carries a second block, `:root[data-theme="dark"]{ … }`, right
after the palette. The gallery switches it on with a tiny script that sets
`data-theme` on `<html>` (stored choice, else `prefers-color-scheme`). The
generated pages have no such script, so this module emits the same block twice:
once as-is (for a page that does set the attribute) and once wrapped in
`@media (prefers-color-scheme: dark)` scoped to `:root:not([data-theme="light"])`,
so `sources/*.html` and `schedule*.html` follow the visitor's system setting.
The dark values are therefore still written exactly once, in `index.html`.

Legacy aliases
--------------
`sources/*.html` was written against a different token vocabulary (`--panel`,
`--border`, `--chip-bg`, `--ok-bg`/`--ok-tx`, …). Rather than rewrite every
rule in that generator, the emitted stylesheet maps those names onto the
canonical ones in an alias block. New rules should use the canonical tokens;
the aliases exist so the port did not have to touch ~80 unrelated CSS lines.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The palette lives in the `:root` block that defines `--bg`. index.html has a
# second, earlier `:root` (layout/threshold tokens only), so anchoring on the
# token rather than on "the first :root" is deliberate.
ROOT_ANCHOR = "--bg:"
# The dark palette is its own block, anchored on its selector.
DARK_ANCHOR = ':root[data-theme="dark"]{'

FONT_LINK_RE = re.compile(
    r'<link\s+rel="stylesheet"\s+href="(https://fonts\.googleapis\.com/css2\?[^"]+)"',
    re.I,
)

GENERATED_HEADER = """/* ---------------------------------------------------------------------------
 * GENERATED FILE — DO NOT EDIT.
 *
 * Built from index.html's :root block by scripts/build_theme.py (#221).
 * index.html is the single source of truth for the palette and the type stack;
 * change it there and re-run:
 *
 *     python scripts/build_theme.py
 *
 * Linked by the generated standalone pages — sources/*.html
 * (scripts/build_source_pages.py) and schedule*.html (R/render_schedule.R) —
 * so they cannot drift away from the gallery's design.
 * --------------------------------------------------------------------------- */
"""

# Base element styles shared by every generated page. Kept here rather than in
# each generator so "same palette AND same type" is one decision.
BASE_RULES = """
*, *::before, *::after { box-sizing: border-box; }

html {
  background: var(--bg);
}

body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

/* Serifs in headings, never in running text — the redesign's type rule. */
h1, h2, h3, h4 {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--text);
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

code, kbd, samp, pre { font-family: var(--mono); font-size: .9em; }

hr { border: 0; border-top: 1px solid var(--line); margin: 28px 0; }

::selection { background: var(--accent-wash); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: .01ms !important;
    animation-duration: .01ms !important;
  }
}
"""

# Vocabulary used by sources/*.html before #221. Mapped rather than rewritten;
# see the module docstring.
LEGACY_ALIASES = """
/* Legacy token names used by sources/*.html, mapped onto the canonical ones
   above so that generator's existing rules keep working. Prefer the canonical
   names in anything new.

   This list is exactly the four aliases build_source_pages.py still references
   — not every name the old dark palette defined. An alias nothing uses is the
   kind of thing that outlives its reason, so it is not carried over on spec. */
:root {
  --panel: var(--surface);
  --border: var(--line);
  --chip-bg: var(--accent-wash);
  --ok-tx: var(--ok);
}
"""


def _brace_block(html: str, start: int, what: str) -> str:
    """Return html[start:] up to and including the brace that closes the first
    `{` after `start`. Brace-matched, not regexed (see _extract_root_block)."""
    open_brace = html.find("{", start)
    if open_brace == -1:
        raise SystemExit(f"ERROR: malformed {what} in index.html.")
    depth = 0
    for i in range(open_brace, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    raise SystemExit(f"ERROR: unbalanced braces in index.html's {what}.")


def _extract_dark_block(html: str) -> str:
    """Return the *body* of the `:root[data-theme="dark"]{ … }` block (the
    declarations between the braces), so it can be re-wrapped under two
    selectors. Strict like the light block: a missing dark palette fails."""
    start = html.find(DARK_ANCHOR)
    if start == -1:
        raise SystemExit(
            f"ERROR: no '{DARK_ANCHOR}' block found in index.html — the dark "
            "palette moved or was renamed. Fix scripts/build_theme.py before shipping."
        )
    block = _brace_block(html, start, "dark :root block")
    return block[len(DARK_ANCHOR):-1].strip("\n")


def _extract_root_block(html: str) -> str:
    """Return the `:root{ … }` block that carries the palette, braces included.

    Brace-matched rather than regexed to the closing `}`: the block contains
    nested `{` only in comments today, but a future `@supports` inside it would
    silently truncate a lazy match.
    """
    anchor = html.find(ROOT_ANCHOR)
    if anchor == -1:
        raise SystemExit(
            f"ERROR: no '{ROOT_ANCHOR}' found in index.html — the palette block "
            "moved or was renamed. Fix scripts/build_theme.py before shipping."
        )
    start = html.rfind(":root", 0, anchor)
    if start == -1:
        raise SystemExit("ERROR: '--bg:' is not inside a :root block in index.html.")

    open_brace = html.find("{", start)
    if open_brace == -1 or open_brace > anchor:
        raise SystemExit("ERROR: malformed :root block in index.html.")

    depth = 0
    for i in range(open_brace, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    raise SystemExit("ERROR: unbalanced braces in index.html's :root block.")


def _extract_font_href(html: str) -> str:
    m = FONT_LINK_RE.search(html)
    if not m:
        raise SystemExit(
            "ERROR: no Google Fonts <link> found in index.html — the type stack "
            "moved. Fix scripts/build_theme.py before shipping."
        )
    return m.group(1)


def build_css(html: str) -> str:
    root = _extract_root_block(html)
    dark = _extract_dark_block(html)
    font_href = _extract_font_href(html)
    indented = "\n".join(("  " + ln) if ln.strip() else ln for ln in dark.split("\n"))
    return (
        GENERATED_HEADER
        # @import must precede every rule, so it goes first.
        + f"\n@import url('{font_href}');\n\n"
        + root.rstrip()
        + "\n\n"
        + "/* Dark palette, set explicitly by a page script ... */\n"
        + DARK_ANCHOR + "\n" + dark + "\n}\n\n"
        + "/* ... or following the visitor's system setting when no script does. */\n"
        + '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]){\n'
        + indented + "\n  }\n}\n\n"
        + LEGACY_ALIASES.strip()
        + "\n\n"
        + BASE_RULES.strip()
        + "\n"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--index", default="index.html", type=Path,
                   help="Source of truth (default: %(default)s)")
    p.add_argument("--out", default="assets/theme.css", type=Path,
                   help="Generated stylesheet (default: %(default)s)")
    p.add_argument("--check", action="store_true",
                   help="Verify --out matches --index; write nothing. Exit 1 on drift.")
    args = p.parse_args(argv)

    if not args.index.exists():
        print(f"ERROR: {args.index} not found", file=sys.stderr)
        return 2

    css = build_css(args.index.read_text(encoding="utf-8"))

    if args.check:
        if not args.out.exists():
            print(f"ERROR: {args.out} does not exist; run scripts/build_theme.py",
                  file=sys.stderr)
            return 1
        if args.out.read_text(encoding="utf-8") != css:
            print(
                f"ERROR: {args.out} is out of date with {args.index}.\n"
                "       Run: python scripts/build_theme.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.out} matches {args.index}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(css, encoding="utf-8")
    n_tokens = css.count("--", 0, css.find("Legacy token names"))
    print(f"Wrote {args.out} ({len(css):,} bytes, ~{n_tokens} tokens)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
