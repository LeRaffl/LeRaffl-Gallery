#!/usr/bin/env python3
"""Offline HTTP-contract regressions; never contact SIMI or write real data."""
import copy
import html
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import fetch_ireland as fi

FIXTURE = json.loads((Path(__file__).parent / "fixtures/ireland/maintenance.json").read_text())


def response(status=200, payload=None, text=None, kind="application/json", **headers):
    r = requests.Response()
    r.status_code = status
    r.url = fi.BASE + "/"
    r.headers.update({"Content-Type": kind, **headers})
    r._content = (json.dumps(payload) if text is None else text).encode()
    r.encoding = "utf-8"
    return r


def bootstrap(component="Public/Passenger", version="fixture-version"):
    page = {"component": component, "version": version, "props": {}}
    return response(text='<div data-page="' + html.escape(json.dumps(page), quote=True) + '"></div>',
                    kind="text/html")


def page(variant="Whole", props=None):
    return response(payload={"component": fi.VARIANT_CONFIG[variant]["component"],
                             "props": props if props is not None else {"carsByEngineType": {"datasets": []}}})


def dataset(labels=None):
    labels = labels if labels is not None else {"Electric": 100, "Petrol": 200}
    return {"years": [2026], "datasets": [
        {"label": k, "units": [{"count": v, "change": 0}]} for k, v in labels.items()]}


def client(*gets, patches=None):
    c = fi.SimiClient()
    c.s = Mock()
    c.s.cookies = {"XSRF-TOKEN": "offline-only"}
    c.s.get.side_effect = gets
    c.s.patch.side_effect = patches or [response(303, Location=fi.BASE + "/")]
    c.version = "fixture-version"
    return c


class SourceContractTests(unittest.TestCase):
    def test_observed_maintenance_redirect_fails_at_bootstrap_before_patch(self):
        evidence = FIXTURE["partial_get"]
        c = client(response(evidence["status"], text="", **evidence["headers"]))
        with self.assertRaisesRegex(fi.SimiSourceError, "updating"):
            c.bootstrap()
        c.s.patch.assert_not_called()
        self.assertFalse(c.s.get.call_args.kwargs["allow_redirects"])

    def test_maintenance_component_is_not_a_passenger_bootstrap(self):
        c = client(bootstrap(FIXTURE["destination_page"]["component"]))
        with self.assertRaisesRegex(fi.SimiSourceError, "expected Public/Passenger"):
            c.bootstrap()
        c.s.patch.assert_not_called()

    def test_bootstrap_healthy_and_invalid_pages(self):
        c = client(bootstrap())
        c.bootstrap()
        self.assertEqual(c.version, "fixture-version")
        cases = [response(text="", kind="text/html"),
                 response(text='<div data-page="{bad}"></div>', kind="text/html"),
                 bootstrap("Auth/Login"), bootstrap(version=None),
                 response(503, text="Unavailable", kind="text/html"),
                 response(302, text="", Location=fi.BASE + "/login")]
        for r in cases:
            with self.subTest(status=r.status_code, body=r.text):
                with self.assertRaises(fi.SimiSourceError):
                    client(r).bootstrap()
        c = client(bootstrap())
        c.s.cookies = {}
        with self.assertRaisesRegex(fi.SimiSourceError, "cookie"):
            c.bootstrap()

    def test_all_routes_and_filter_shapes_use_one_flow(self):
        for variant, cfg in fi.VARIANT_CONFIG.items():
            with self.subTest(variant=variant):
                c = client(page(variant, {"carsByEngineType": dataset()}),
                           patches=[response(303, Location=fi.BASE + "/" + cfg["route"])])
                self.assertEqual(c.fetch_month(variant, 2026, 7), {"BEV": 100, "PETROL": 200})
                args, kw = c.s.patch.call_args
                self.assertEqual(args[0], fi.BASE + "/filter/" + cfg["filter"])
                body = json.loads(kw["data"])
                self.assertEqual(body["years"], [{"name": 2026, "value": 2026}])
                self.assertEqual(body["month_from"], {"name": "July", "value": 7})
                self.assertEqual(body["month_to"], body["month_from"])
                self.assertEqual(body["registration_type"]["value"], "new-total")
                self.assertEqual(body["engine_types"], [])
                self.assertFalse(kw["allow_redirects"])
                self.assertEqual(c.s.get.call_args.args[0], fi.BASE + "/" + cfg["route"])
                self.assertEqual(c.s.get.call_args.kwargs["headers"]["X-Inertia-Partial-Component"], cfg["component"])
                self.assertFalse(c.s.get.call_args.kwargs["allow_redirects"])

    def test_existing_200_and_relative_redirect_filter_responses_still_work(self):
        for accepted in [response(200), response(302, Location="/")]:
            c = client(page(props={"carsByEngineType": dataset()}), patches=[accepted])
            self.assertEqual(c.fetch_month("Whole", 2026, 7), {"BEV": 100, "PETROL": 200})

    def test_partial_rejects_maintenance_non_json_empty_http_errors_and_wrong_props(self):
        cases = [response(302, text="", Location=fi.BASE + "/updating"),
                 response(409, text="", **{"X-Inertia-Location": fi.BASE + "/updating"}),
                 response(302, text="", Location=fi.BASE + "/login"),
                 response(409, text="Version mismatch"), response(503, text="Unavailable"),
                 response(204, text=""), response(text="<html>error</html>", kind="text/html"),
                 response(text=""), response(text="not json"), response(payload=None),
                 response(payload=[]), response(payload={}),
                 response(payload={"component": "Public/Updating", "props": {}}),
                 page(props={"renamedProp": {}}),
                 page(props={"carsByEngineType": {}, "errors": {"years": "invalid"}})]
        for r in cases:
            with self.subTest(status=r.status_code, body=r.text):
                with self.assertRaises(fi.SimiSourceError):
                    client(r).fetch_month("Whole", 2026, 7)

    def test_failed_filter_never_triggers_partial_get(self):
        cases = [response(419, text="expired"), response(422, payload={"errors": {}}),
                 response(500, text="error"), response(303, Location=fi.BASE + "/updating"),
                 response(302, Location=fi.BASE + "/login"),
                 response(303, Location="https://example.invalid/"), response(303)]
        for r in cases:
            with self.subTest(status=r.status_code, headers=dict(r.headers)):
                c = client(patches=[r])
                with self.assertRaises(fi.SimiSourceError):
                    c.fetch_month("Whole", 2026, 7)
                c.s.get.assert_not_called()

    def test_network_error_is_not_a_zero_month(self):
        c = client(requests.Timeout("offline timeout"))
        with self.assertRaises(requests.Timeout):
            c.fetch_month("Whole", 2026, 7)

    def test_missing_or_invalid_dataset_cannot_be_silently_skipped(self):
        cases = [None, {}, [], {"datasets": None}, {"datasets": {}},
                 {"datasets": [None]}]
        for ce in cases:
            with self.subTest(dataset=ce):
                with self.assertRaises(fi.SimiSourceError):
                    client(page(props={"carsByEngineType": ce})).fetch_month("Whole", 2026, 7)

    def test_missing_and_invalid_counts_are_not_zero(self):
        for count in [None, "", "bad", -1, 1.5, True, float("nan"), float("inf")]:
            with self.subTest(count=count):
                with self.assertRaises(fi.SimiSourceError):
                    client(page(props={"carsByEngineType": dataset({"Electric": count})})).fetch_month("Whole", 2026, 7)
        for units in [None, [{"count": 1}, {"count": 2}], [{}]]:
            ce = dataset()
            ce["datasets"][0]["units"] = units
            with self.subTest(units=units):
                with self.assertRaises(fi.SimiSourceError):
                    client(page(props={"carsByEngineType": ce})).fetch_month("Whole", 2026, 7)

    def test_listed_label_with_empty_units_is_explicit_zero(self):
        ce = dataset({"Electric": 7, "Petrol": 3})
        ce["datasets"][1]["units"] = []
        cols = client(page(props={"carsByEngineType": ce})).fetch_month("Whole", 2026, 7)
        self.assertEqual(cols[fi.LABEL_TO_COL["Petrol"]], 0.0)
        self.assertEqual(sum(cols.values()), 7.0)

    def test_all_existing_fuel_buckets_and_total_are_unchanged(self):
        labels = {name: i for i, name in enumerate(fi.LABEL_TO_COL, 1)}
        ce = dataset(labels)
        original = copy.deepcopy(ce)
        cols = client(page(props={"carsByEngineType": ce})).fetch_month("Whole", 2026, 7)
        expected = {}
        for label, count in labels.items():
            col = fi.LABEL_TO_COL[label]
            expected[col] = expected.get(col, 0) + count
        self.assertEqual(cols, expected)
        row = fi.row_from_cols("Whole", "2026-07", cols)
        self.assertEqual(row["TOTAL"], sum(labels.values()))
        self.assertEqual(list(row), fi.CSV_COLUMNS)
        self.assertEqual(row["notes"], "")
        self.assertEqual(ce, original)
        self.assertEqual(cols["OTHERS"], sum(labels[n] for n in ("Gas", "Petrol / Gas", "Diesel / Gas", "Hydrogen", "Other")))

    def test_explicit_empty_dataset_or_zero_retains_existing_no_row_policy(self):
        for ce in [{"datasets": []}, dataset({"Electric": 0, "Diesel": "0"})]:
            cols = client(page(props={"carsByEngineType": ce})).fetch_month("Whole", 2026, 7)
            self.assertIsNone(fi.row_from_cols("Whole", "2026-07", cols))

    def test_unknown_label_remains_a_hard_error(self):
        with self.assertRaisesRegex(fi.SimiSourceError, "unmapped"):
            client(page(props={"carsByEngineType": dataset({"New engine": 1})})).fetch_month("Whole", 2026, 7)

    def test_rankings_share_checked_transport_and_preserve_extra_filters(self):
        c = client(page(props={"carsByMake": {"datasets": []}, "carsByModel": {"datasets": []}}))
        extra = {"engine_types": [{"name": "Electric", "value": "03"}]}
        got = c.partial("Whole", 2026, 7, "carsByMake,carsByModel", extra)
        self.assertEqual(set(got), {"carsByMake", "carsByModel"})
        self.assertEqual(json.loads(c.s.patch.call_args.kwargs["data"])["engine_types"], extra["engine_types"])
        self.assertEqual(c.s.get.call_args.kwargs["headers"]["X-Inertia-Partial-Data"], "carsByMake,carsByModel")

    def test_error_mid_window_preserves_exact_historical_file_bytes(self):
        # Quoted multiline notes, scientific notation, unknown optional column,
        # CRLF and no final newline are deliberately not normalized on failure.
        original = b'period,time_interval,variant,source,BEV,TOTAL,notes,extra\r\n2020-01,monthly,Whole,legacy,1.00e+02,200.00,"a, note\r\nquoted ""text""",keep'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "Ireland.csv"
            path.write_bytes(original)
            c = Mock()
            c.fetch_month.side_effect = [{"BEV": 10, "PETROL": 90}, fi.SimiSourceError("updating")]
            with (patch.dict(fi.VARIANT_CONFIG, {"Whole": {"csv": str(path)}}),
                  patch.object(fi, "upsert_csv") as writer):
                with self.assertRaises(fi.SimiSourceError):
                    fi.run_variant(c, "Whole", (2026, 7), (2026, 8))
                writer.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_main_maintenance_fails_before_any_csv_or_market_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {}
            for cfg in fi.VARIANT_CONFIG.values():
                path = root / cfg["csv"]
                path.parent.mkdir(exist_ok=True)
                files[path] = b'period,variant,BEV,notes\r\n2008-01,Whole,1.00e+02,"keep, untouched"'
                path.write_bytes(files[path])
            c = client(response(302, Location=fi.BASE + "/updating"))
            cwd = os.getcwd()
            try:
                os.chdir(root)
                with (patch.object(fi, "SimiClient", return_value=c),
                      patch.object(fi.sys, "argv", ["fetch_ireland.py", "--force"]),
                      patch.object(fi, "upsert_csv") as writer,
                      patch.object(fi.market_top, "guarded") as market):
                    with self.assertRaises(fi.SimiSourceError):
                        fi.main()
                    writer.assert_not_called()
                    market.assert_not_called()
            finally:
                os.chdir(cwd)
            self.assertEqual({p: p.read_bytes() for p in files}, files)
            c.s.patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
