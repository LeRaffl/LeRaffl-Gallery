#!/usr/bin/env python3
"""
TEMPORARY: dump every HS-8703.80 (electric) row — code + FULL description +
quantity — from the FY 2075/76 and FY 2076/77 annual workbooks, to decide
whether the pre-2020 electric tariff codes (87038010/87038090) can be split
into the same Whole vs 3-Wheelers definition as the monthly era. Read-only.
Removed once the decision is made.
"""
import io
import sys
from pathlib import Path

import openpyxl
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_nepal as fn  # noqa: E402

FYS = [2076, 2075, 2074, 2073]
OUT = Path("scratch_nepal/elec_codes.txt")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(fn.HTTP_HEADERS)
    cats = fn.discover_fy_categories(session)
    lines = []
    for fy in FYS:
        lines.append(f"\n===== FY {fy}/{(fy+1)%100:02d}")
        content = fn.find_fts_content_page(session, fy, cats.get(fy, []))
        picked = fn._pick_annual_workbook(session, content) if content else None
        if picked is None:
            lines.append("  (no annual)")
            continue
        data, origin = picked
        lines.append(f"  {origin}")
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = fn._find_import_sheet(wb, origin)
        # locate header
        cols = None
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in (row or [])]
            low = [c.lower() for c in cells]
            if cols is None:
                if any(c in fn.CODE_HEADERS for c in low) and "quantity" in low \
                        and "description" in low and "unit" in low:
                    ci = next(i for i, c in enumerate(low) if c in fn.CODE_HEADERS)
                    cols = {"code": ci, "desc": low.index("description"),
                            "qty": low.index("quantity")}
                continue
            code = cells[cols["code"]]
            if code.endswith(".0"):
                code = code[:-2]
            if code.startswith("870380"):
                lines.append(f"    {code}  qty={cells[cols['qty']]:>8}  {cells[cols['desc']]!r}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
