# bands/

**Generated — do not hand-edit.** One `<slug>.json` per rendered series (same
slug as in `images/`), written by `R/bands.R` from `R/render_country.R` on every
render.

Each file holds the 95 % **confidence** (the true curve), **prediction** (one
more month) and **tolerance** (95 % of all months, 95 % confidence) bands around
the fitted S-curve, in calendar decimal years, plus the 10/20/50/80/90 %
crossing years with their confidence ranges.

These are frontend data only; the PNGs in `images/` do not use them.

**Check `quality.usable` before using a file.** `false` means the band must
not be shown or quoted: the series is too short (fewer than 48 data points) or
the S-curve fits it poorly (`quality.reasons`).

What the three bands mean, how they are computed and validated, and how to
quote them correctly: [`docs/architecture/44-uncertainty-bands.md`](../docs/architecture/44-uncertainty-bands.md).
