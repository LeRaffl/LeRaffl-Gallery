#!/usr/bin/env python3
"""Offline regressions for Japan's CSV writer: python scripts/test_fetch_japan.py.

No source requests or repository data writes; each test uses a temporary CSV.
The parser/fuel mapping is intentionally outside this writer-only repair.
"""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fetch_japan as fj


class JapanUpsertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "Japan.csv"
        self.header = ",".join(fj.CSV_COLUMNS)

    def row(self, period="2026-02", **changes):
        row = fj.build_row(period, dict(BEV=10, PHEV=20, HEV=30,
                                       PETROL=40, DIESEL=50, OTHERS=1, TOTAL=151),
                           "https://example.test/jada.xlsx")
        row.update(changes)
        return row

    def record(self, row, columns=None, eol="\r\n"):
        out = io.StringIO(newline="")
        csv.writer(out, lineterminator="\r\n").writerow(
            [row.get(c, "") for c in (columns or fj.CSV_COLUMNS)])
        return out.getvalue()[:-2] + eol

    def write(self, text):
        self.path.write_bytes(text.encode("utf-8"))

    def read(self):
        return self.path.read_bytes().decode("utf-8")

    def upsert(self, row=None, force=False):
        row = self.row() if row is None else row
        return fj.upsert_row(str(self.path), row["period"], row, force)

    def parsed(self):
        return list(csv.DictReader(io.StringIO(self.read(), newline="")))

    def test_new_and_empty_files_use_canonical_schema(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.write("")
                self.assertTrue(self.upsert())
                self.assertEqual(self.read(), self.header + "\n" + self.record(self.row(), eol="\n"))
                self.path.unlink()

    def test_insert_preserves_historical_bytes_and_crlf(self):
        old = self.row("2026-01", BEV="1e1", PHEV="20.0000", TOTAL="1.510e2",
                       source="historical source", notes='comma, quote " and NEL \x85')
        before = self.header + "\r\n" + self.record(old)
        self.write(before)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), before + self.record(self.row()))

    def test_insert_before_later_period_preserves_both_neighbours(self):
        first = self.record(self.row("2026-01", BEV="1e1"))
        last = self.record(self.row("2026-03", notes="untouched"), eol="")
        self.write(self.header + "\r\n" + first + last)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), self.header + "\r\n" + first + self.record(self.row()) + last)

    def test_existing_key_without_force_never_writes(self):
        before = self.header + "\r\n" + self.record(self.row(BEV="1.000e1"), eol="")
        self.write(before)
        with patch.object(Path, "write_bytes", side_effect=AssertionError("must not write")):
            self.assertFalse(self.upsert(self.row(BEV=99)))
        self.assertEqual(self.read(), before)

    def test_force_replaces_only_target_keeps_its_lf_ending(self):
        first = self.record(self.row("2026-01", BEV="1e1"))
        last = self.record(self.row("2026-03", notes="untouched"), eol="")
        self.write(self.header + "\r\n" + first + self.record(self.row(), eol="\n") + last)
        changed = self.row(BEV=11.0, TOTAL=152.0)
        self.assertTrue(self.upsert(changed, force=True))
        self.assertEqual(self.read(), self.header + "\r\n" + first
                         + self.record(changed, eol="\n") + last)

    def test_same_period_other_variant_does_not_block_insert(self):
        other = self.record(self.row(variant="Used", notes="do not touch"))
        self.write(self.header + "\r\n" + other)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), self.header + "\r\n" + other + self.record(self.row()))
        # Historical order remains intact, even when it is not sorted by variant.
        self.assertEqual([r["variant"] for r in self.parsed()], ["Used", "Whole"])

    def test_same_period_other_variant_survives_force(self):
        other = self.record(self.row(variant="Used"))
        self.write(self.header + "\r\n" + other + self.record(self.row()))
        changed = self.row(BEV=12)
        self.assertTrue(self.upsert(changed, force=True))
        self.assertEqual(self.read(), self.header + "\r\n" + other + self.record(changed))

    def test_header_order_and_unknown_columns_survive_update(self):
        cols = ["notes", "optional", *[c for c in fj.CSV_COLUMNS if c != "notes"]]
        header = self.record(dict(zip(cols, cols)), cols, "\n")
        old = self.row(optional='001.2300, "custom"\nsecond line')
        self.write(header + self.record(old, cols, "\n"))
        self.assertTrue(self.upsert(self.row(BEV=11), force=True))
        self.assertTrue(self.read().startswith(header))
        self.assertEqual(self.parsed()[0]["optional"], old["optional"])
        self.assertEqual(self.parsed()[0]["BEV"], "11")

    def test_new_row_leaves_unknown_column_empty(self):
        cols = fj.CSV_COLUMNS + ["optional"]
        old = self.record(self.row("2026-01", optional="old extra"), cols)
        header = ",".join(cols) + "\r\n"
        self.write(header + old)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), header + old + self.record(self.row(), cols))
        self.assertEqual(self.parsed()[1]["optional"], "")

    def test_multiline_quoted_notes_are_logical_records(self):
        old = self.record(self.row("2026-01", notes='line 1, "quoted"\r\nline 2\nline 3'))
        self.write(self.header + "\r\n" + old)
        new = self.row(notes='new, "quoted"\nsecond line')
        self.assertTrue(self.upsert(new))
        self.assertEqual(self.read(), self.header + "\r\n" + old + self.record(new))
        self.assertEqual(self.parsed()[-1]["notes"], new["notes"])
        self.assertTrue(self.upsert(self.row(notes="replacement"), force=True))
        self.assertTrue(self.read().startswith(self.header + "\r\n" + old))

    def test_lf_writer_quotes_embedded_carriage_return(self):
        self.write(self.header + "\n")
        row = self.row(notes="one\rtwo")
        self.assertTrue(self.upsert(row))
        self.assertEqual(self.parsed()[0]["notes"], "one\rtwo")
        self.assertTrue(self.read().endswith('"one\rtwo"\n'))

    def test_mixed_record_endings_are_preserved(self):
        first = self.record(self.row("2026-01"), eol="\n")
        last = self.record(self.row("2026-03"), eol="\r\n")
        self.write(self.header + "\r\n" + first + last)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), self.header + "\r\n" + first + self.record(self.row()) + last)

    def test_bare_cr_record_endings(self):
        before = self.header + "\r" + self.record(self.row("2026-01"), eol="\r")
        self.write(before)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), before + self.record(self.row(), eol="\r"))

    def test_append_to_unterminated_file_adds_only_separator(self):
        before = self.header + "\r\n" + self.record(self.row("2026-01"), eol="")
        self.write(before)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), before + "\r\n" + self.record(self.row(), eol=""))

    def test_header_only_without_final_newline(self):
        self.write(self.header)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), self.header + "\n" + self.record(self.row(), eol=""))

    def test_replacement_preserves_missing_final_newline(self):
        self.write(self.header + "\n" + self.record(self.row(), eol=""))
        changed = self.row(BEV=11)
        self.assertTrue(self.upsert(changed, force=True))
        self.assertEqual(self.read(), self.header + "\n" + self.record(changed, eol=""))

    def test_repeated_forced_row_is_noop_without_write(self):
        self.assertTrue(self.upsert())
        before = self.path.read_bytes()
        with patch.object(Path, "write_bytes", side_effect=AssertionError("must not write")):
            self.assertFalse(self.upsert(force=True))
            self.assertFalse(self.upsert())
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_record_order_and_blank_records_are_not_sorted_away(self):
        later = self.record(self.row("2026-04"))
        earlier = self.record(self.row("2026-01"))
        self.write(self.header + "\r\n" + later + "\r\n" + earlier)
        self.assertTrue(self.upsert())
        self.assertEqual(self.read(), self.header + "\r\n" + self.record(self.row())
                         + later + "\r\n" + earlier)

    def test_invalid_inputs_fail_before_writing(self):
        good = self.header + "\n" + self.record(self.row(), eol="\n")
        bad_files = ["period,source\n2026-02,JADA\n",
                     good + self.record(self.row(), eol="\n"),
                     self.header + '\n2026-01,"unterminated',
                     self.header + "\n2026-01,too,few\n",
                     self.header + ",period\n"]
        for before in bad_files:
            with self.subTest(before=before):
                self.write(before)
                with self.assertRaises((ValueError, csv.Error)):
                    self.upsert(force=True)
                self.assertEqual(self.read(), before)

    def test_new_field_not_in_schema_is_not_silently_dropped(self):
        before = self.header + "\n"
        self.write(before)
        with self.assertRaisesRegex(ValueError, "absent from CSV header"):
            self.upsert(self.row(unexpected=42))
        self.assertEqual(self.read(), before)

    def test_period_argument_must_match_row(self):
        with self.assertRaisesRegex(ValueError, "match period"):
            fj.upsert_row(str(self.path), "2026-01", self.row(), False)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
