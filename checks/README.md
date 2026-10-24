# checks/

**Hand-kept** reference figures that a fetcher compares its own months with —
numbers other people publish that no fetcher can read reliably (press articles,
police press conferences). Unlike `market/` and `data/raw/`, these files are
edited by hand; the comparison result is generated into `market/<slug>_checks.json`
([03 §3.16b](../docs/architecture/03-data-objects.md)) and shown on the country's
source page under "Why other figures differ".

| file | read by | reminder |
|---|---|---|
| `vietnam_reference.csv` | `scripts/check_vietnam_reference.py` (run by `fetch-vietnam.yml`, also on every push of this file) | `vietnam-reference-reminder.yml` — one issue labelled `vietnam-reference` while a figure is due |

`vietnam_reference.csv` columns: `kind` (`media_total` = one month, every vehicle
type; `media_year` = a calendar year; `csgt` = police registrations, dates as
published), `period_from`, `period_to`, `figure`, `rounded` (`yes` when the
article says "hơn / khoảng / gần"), `url` (the article), `note`. See
[64-source-vietnam.md](../docs/architecture/64-source-vietnam.md) §5.
