#!/usr/bin/env python3
"""--sheet must not restore the quarterly petrol/diesel paste."""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_portugal as fp  # noqa: E402


def main() -> None:
    note = fp.ESTIMATED_SPLIT_PREFIX + ": published mix scaled"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Portugal.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "period", "time_interval", "variant", "source",
                "BEV", "PHEV", "HEV", "PETROL", "DIESEL", "FLEXFUEL",
                "OTHERS", "TOTAL", "notes",
            ])
            w.writeheader()
            w.writerow({
                "period": "2018-01", "time_interval": "monthly", "variant": "Whole",
                "source": "ACAP", "BEV": "1", "PHEV": "1", "HEV": "1",
                "PETROL": "10", "DIESEL": "20", "FLEXFUEL": "", "OTHERS": "1",
                "TOTAL": "33", "notes": note,
            })
            w.writerow({
                "period": "2024-01", "time_interval": "monthly", "variant": "Whole",
                "source": "ACAP", "BEV": "1", "PHEV": "1", "HEV": "1",
                "PETROL": "10", "DIESEL": "20", "FLEXFUEL": "", "OTHERS": "1",
                "TOTAL": "33", "notes": "",
            })
        kept = fp.periods_with_estimated_split(str(path), "Whole")
        assert kept == {"2018-01"}, kept
        assert fp.periods_with_estimated_split(str(path), "Vans") == set()
    print("ok")


if __name__ == "__main__":
    main()
