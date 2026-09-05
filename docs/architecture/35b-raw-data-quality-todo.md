# 35b · Raw Data — data-quality checklist

**Generated, not hand-written** — `python3 scripts/build_series.py` rewrites this file on every build. Items disappear when the rows behind them are fixed, so `git diff` on this file is the progress report. Nothing here is a rendering bug: every entry is a statement about what is in `data/<Country>.csv`, phrased so it can be checked against the file.

**Status:** 51 countries · 6,014 periods drawable · 164 held back · **37 of 51 files cost the chart nothing.**

---

## Tier 1 — costs bars

Ordered by what it costs. A period lost at T1M costs up to twelve bars at T12M, because a trailing window needs every month inside it (§ 7b), so the *Symptom* line is usually much larger than the row count above it.

### Japan  ·  costs 96 periods

- [ ] `2025-11` — OTHERS drops to 0 between 57 and 31. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] **94 rows where `OTHERS` carries more than 80% of `TOTAL`** — the source broke out almost nothing, so there is no mix to stack · 2012-01…2019-10
- [ ] **2 rows with an exactly-zero combustion side** — only the EV columns were filled and `TOTAL` computed from them · 2019-11…2019-12

### Portugal  ·  costs 88 periods

- [ ] **31 rows whose bands do not add up to `TOTAL`** (worst 2018-01: bands miss TOTAL by +43.6%) · 2018-01, 2018-03…2018-04, 2018-06…2018-07 …
- [ ] **13 rows in an incomplete cycle** — the coarse figure they carry needs the whole cycle present to be summed back (incomplete 3-month cycle (2 of 3 rows present)) · 2017-08…2017-10, 2018-02, 2018-05 …
→ *Symptom:* 4 visible gaps in the chart, 44 months (worst 2018-01…2020-03).

### Singapore  ·  costs 23 periods

- [ ] `2022-12` — HEV drops to 0 between 930 and 776. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] **No rows for 2019-02…2019-12** — 11 periods the CSV says nothing about.
- [ ] **6 rows in an incomplete cycle** — the coarse figure they carry needs the whole cycle present to be summed back (incomplete 12-month cycle (6 of 12 rows present)) · 2022-01…2022-06
→ *Symptom:* 2 visible gaps in the chart, 17 months (worst 2019-02…2020-12).

### Poland  ·  costs 12 periods

- [ ] `2019-06` — OTHERS drops to 0 between 2040 and 1544.59. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] `2021-01` — OTHERS drops to 0 between 2885.19 and 84.642. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] **4 rows whose bands do not add up to `TOTAL`** (worst 2018-02: bands miss TOTAL by +10.5%) · 2018-02…2018-03, 2018-05…2018-06
- [ ] **2 rows in an incomplete cycle** — the coarse figure they carry needs the whole cycle present to be summed back (incomplete 3-month cycle (1 of 3 rows present)) · 2018-01, 2018-04
→ *Symptom:* 1 visible gap in the chart, 6 months (worst 2018-01…2018-09).

### Malta  ·  costs 9 periods

- [ ] **No rows for 2025-07…2026-03** — 9 periods the CSV says nothing about.
→ *Symptom:* 1 visible gap in the chart, 9 months (worst 2025-07…2026-04).

### Slovenia  ·  costs 9 periods

- [ ] **3 rows whose bands do not add up to `TOTAL`** (worst 2017-06: bands miss TOTAL by +34.4%) · 2015-06, 2016-06, 2017-06
- [ ] **3 rows in an incomplete cycle** — the coarse figure they carry needs the whole cycle present to be summed back (incomplete 3-month cycle (2 of 3 rows present)) · 2020-02…2020-04
→ *Symptom:* 1 visible gap in the chart, 3 months (worst 2020-02…2020-05).

### Australia  ·  costs 6 periods

- [ ] **No rows for 2020-01…2020-06** — 6 periods the CSV says nothing about.
→ *Symptom:* 1 visible gap in the chart, 6 months (worst 2020-01…2020-07).

### Iceland  ·  costs 6 periods

- [ ] **3 rows whose bands do not add up to `TOTAL`** (worst 2019-01: bands miss TOTAL by +7.4%) · 2019-01, 2019-03…2019-04
→ *Symptom:* 2 visible gaps in the chart, 3 months (worst 2019-03…2019-05).

### China  ·  costs 2 periods

- [ ] **1 rows in an incomplete cycle** — the coarse figure they carry needs the whole cycle present to be summed back (incomplete 3-month cycle (1 of 3 rows present)) · 2020-03
→ *Symptom:* 1 visible gap in the chart, 1 months (worst 2020-03…2020-06).

### Uruguay  ·  costs 2 periods

- [ ] **2 rows with an exactly-zero combustion side** — only the EV columns were filled and `TOTAL` computed from them · 2021-06, 2022-06

### Costs no bars, but still wrong

**Belgium**
- [ ] `2022-03` — OTHERS drops to 0 between 258 and 171. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] `2023-02` — OTHERS drops to 0 between 281 and 403. The row still closes to `TOTAL`, so no sum check sees it.
- [ ] `2023-09` — OTHERS drops to 0 between 151 and 224. The row still closes to `TOTAL`, so no sum check sees it.

**Colombia**
- [ ] `2020-04` — BEV drops to 0 between 110 and 51. The row still closes to `TOTAL`, so no sum check sees it.

**Norway**
- [ ] `2009-01` — BEV drops to 0 between 65 and 28. The row still closes to `TOTAL`, so no sum check sees it.

**Romania**
- [ ] `2021-12` — OTHERS drops to 0 between 43 and 1420. The row still closes to `TOTAL`, so no sum check sees it.

---

## Tier 2 — the shape of the file

Real, and already handled by the pipeline. Listed so the provenance of each file is on record and so nobody re-discovers it as a bug. Fixing these buys resolution, not bars.

### Austria

- A coarse figure is written across finer rows in **`BEV`, `TOTAL`** — up to 72 rows, 2012-01…2017-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Belgium

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 48 rows, 2018-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 57 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Bulgaria

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 48 rows, 2018-01…2022-01. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### China

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `ICE`, `TOTAL`** — up to 127 rows, 2010-01…2020-09. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **yearly** on 82 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Croatia

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 27 rows, 2019-10…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Cyprus

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `TOTAL`** — up to 24 rows, 2020-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 24 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Estonia

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 48 rows, 2018-01…2024-02. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 48 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Germany

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`** — up to 26 rows, 2012-01…2014-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 36 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Greece

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 48 rows, 2018-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 48 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Hungary

- A coarse figure is written across finer rows in **`HEV`, `PETROL`, `DIESEL`, `OTHERS`** — up to 48 rows, 2018-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Iceland

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 12 rows, 2021-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Italy

- `time_interval` says **quarterly** on 24 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Japan

- A coarse figure is written across finer rows in **`BEV`, `PHEV`** — up to 96 rows, 2012-01…2019-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 97 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Lithuania

- A coarse figure is written across finer rows in **`BEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 60 rows, 2017-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 60 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Luxembourg

- A coarse figure is written across finer rows in **`OTHERS`** — up to 23 rows, 2011-05…2022-03. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Netherlands

- A coarse figure is written across finer rows in **`BEV`, `PHEV`** — up to 72 rows, 2011-01…2016-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### New Zealand

- A coarse figure is written across finer rows in **`OTHERS`** — up to 14 rows, 2016-05…2023-06. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Norway

- A coarse figure is written across finer rows in **`OTHERS`** — up to 9 rows, 2016-02…2022-09. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Poland

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `DIESEL`** — up to 87 rows, 2011-01…2021-06. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 108 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Portugal

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`** — up to 93 rows, 2010-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.

### Romania

- A coarse figure is written across finer rows in **`HEV`, `PETROL`, `DIESEL`, `TOTAL`** — up to 45 rows, 2018-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 26 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Singapore

- A coarse figure is written across finer rows in **`BEV`** — up to 66 rows, 2016-01…2022-06. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **yearly** on 36 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.
- `time_interval` says **quarterly** on 12 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Slovakia

- A coarse figure is written across finer rows in **`BEV`, `PHEV`, `HEV`, `PETROL`, `DIESEL`, `OTHERS`, `TOTAL`** — up to 48 rows, 2018-01…2021-12. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **quarterly** on 48 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

### Türkiye

- A coarse figure is written across finer rows in **`BEV`, `HEV`, `TOTAL`** — up to 36 rows, 2016-01…2022-06. Recovered by summing the cycle; the cycle is then the finest resolution the chart can offer for that span.
- `time_interval` says **yearly** on 36 rows whose spacing is **monthly**. Nothing reads the label except § 3.2b (a row alone in its cycle), but it misleads every future consumer.

---

## Costs the chart nothing

Albania, Austria, Brazil, Bulgaria, Canada, Chile, Croatia, Cyprus, Czechia, Denmark, Estonia, Finland, France, Georgia, Germany, Greece, Hungary, Indonesia, Ireland, Israel, Italy, Latvia, Lithuania, Luxembourg, Malaysia, Nepal, Netherlands, New Zealand, Slovakia, South Korea, Spain, Sweden, Switzerland, Thailand, Türkiye, UK, USA
