# 08 · Deploy and Ops

Operational runbook. How to deploy, how to trigger, how to debug. Commands you can copy.

## Quick reference

| Task | Command | Section |
|---|---|---|
| Deploy worker code change | `cd worker && npx wrangler@latest deploy` | [§ 8.1](#81-deploy-the-worker) |
| Re-render one country | Actions tab → "Render country charts" → Run workflow | [§ 8.2](#82-trigger-a-country-render) |
| Add a new country | Extract CSV, push, run render | [§ 8.3](#83-add-a-new-country) |
| Rotate the Worker's PAT | Edit PAT in GitHub, re-`wrangler secret put` | [§ 8.4](#84-rotate-secrets) |
| Merge a public submission | Review PR diff, click Merge, then [§ 8.2](#82-trigger-a-country-render) | [§ 8.5](#85-process-a-submission-pr) |
| Hide spam feedback | Add `hidden` label to the issue | [§ 8.6](#86-moderate-feedback) |
| Bulk-render all countries | Loop through countries calling [§ 8.2](#82-trigger-a-country-render) one at a time | [§ 8.7](#87-bulk-rerender) |
| Debug Worker errors | Cloudflare dashboard → Workers → Tail logs | [§ 8.8](#88-debugging) |
| Indonesia table shows ~5y 20→80 again | Frontend + backend recovery both already in place — see § "Indonesia v1=0 corruption" | [§ 8.8](#indonesia-v10-corruption) |
| Manually snapshot Builder curves | Actions tab → "Snapshot Builder curves" → Run workflow | [§ 8.9](#89-snapshot-builder-curves) |

## 8.1 Deploy the Worker

Required when **any** of these change:
- `worker/index.js`
- `worker/wrangler.toml` (compat date, KV bindings, account_id, vars)
- The Worker's `GITHUB_TOKEN` secret (set separately, see § 8.4)

```bash
cd /Users/leraffl/Projects/GitHub/LeRaffl-Gallery/worker
npx wrangler@latest deploy
```

**What you should see:**
```
Total Upload: ~20 KiB / gzip: ~6 KiB
Your Worker has access to the following bindings:
  env.RATE_KV       (...)        KV Namespace
  env.GITHUB_OWNER  ("leraffl")  Environment Variable
  env.GITHUB_REPO   ("leraffl-gallery")  Environment Variable
Uploaded leraffl-gallery-feedback (~10 sec)
Deployed leraffl-gallery-feedback triggers (~5 sec)
  https://leraffl-gallery-feedback.xgwvfz7nrb.workers.dev
```

If wrangler prompts about a config diff between local and remote, **say no** and reconcile the diff first (usually means someone tweaked the worker via the Cloudflare dashboard; pull those settings into `wrangler.toml`).

## 8.2 Trigger a country render

Required after:
- Merging a public submission PR
- Pushing new data via local R / direct CSV edit
- Any change to `R/*.R` that affects rendered output

Steps:
1. Open <https://github.com/LeRaffl/LeRaffl-Gallery/actions/workflows/render-country.yml>
2. Click "Run workflow" (top-right)
3. Pick branch `master`
4. Fill `country` (e.g. `Germany`) and `variant` (default `Whole`)
5. Click "Run workflow"

The action takes 30–120 s and commits four PNGs + params/weights row update + posts files. It then dispatches the Build-manifest action explicitly, because workflow commits made with `GITHUB_TOKEN` do not fan out into another push-triggered workflow. GitHub Pages auto-deploys from `master` after each generated commit (Pages-from-branch — there is no separate Pages workflow).

**You can also trigger via gh CLI:**
```bash
gh workflow run render-country.yml -f country=Germany -f variant=Whole
gh run watch  # follow the latest run
```

## 8.3 Add a new country

End-to-end, the cheapest path:

1. **Extract CSV from the source sheet.** The python extractor in past PRs is a good template — copy the loop, adjust `RENAME` if the country has unusual column names, write to `data/<Country>.csv`.
2. **Add to `SD_COUNTRIES`** in `index.html` (alphabetical):
   ```js
   { country: 'NewLand', variants: ['Whole'] },
   ```
3. **Add a flag asset** at `assets/flags/<slug>.png` (lowercase, non-alphanumerics → `_`). Copy from the existing flag store or download from a flag asset library; keep at ~64×40 px or similar.
4. **Update `R/post_text.R::.pt_flag`** to map the country name to its emoji flag (regional indicator pair).
5. **Commit**, push, open PR.
6. After merge, run § 8.2 to render.

## 8.4 Rotate secrets

### Worker GITHUB_TOKEN

If the value didn't leak, just edit the existing fine-grained PAT to extend permissions; the token value stays the same. No `wrangler secret put` needed.

If the value did leak or you want to rotate proactively:
1. <https://github.com/settings/personal-access-tokens> → find `leraffl-gallery-feedback-worker` → "Regenerate token" (or revoke + create new)
2. Copy the new token
3. ```bash
   cd worker
   npx wrangler@latest secret put GITHUB_TOKEN
   # paste the new value when prompted
   ```
4. Verify by submitting a test feedback issue and a test data row, both should succeed.

Required scopes (fine-grained PAT on `LeRaffl/LeRaffl-Gallery`):
- Issues: Read and write
- Contents: Read and write
- Pull requests: Read and write
- Metadata: Read

### Cloudflare wrangler session

```bash
npx wrangler@latest login
```
Browser opens, OAuth flow, session is stored in macOS Keychain. Old session in Keychain is overwritten.

## 8.5 Process a submission PR

When a `submit/<country>-<variant>-<ts>` PR appears:

1. Open the PR. Title is `data: <Country> (<Variant>) — <N> added, <M> corrected`.
2. **Body lists each row** with before/after for corrections and added rows verbatim. Quick-check that the numbers look plausible against the cited source.
3. **Look at the file diff** (Files changed tab). Should be exactly one file: `data/<Country>.csv`. If it touches anything else, that's a bug — close without merging and ping the developer.
4. If the data looks right, click "Merge pull request" → squash recommended.
5. Run § 8.2 with the country to refresh PNGs, params, weights, and posts.
6. After the render commits land, the page auto-refreshes within ~1 minute.

If the data looks wrong:
- Comment on the PR explaining what's off.
- Either close without merging, or push a correction commit to the same branch and merge that.

## 8.6 Moderate feedback

| Action | How |
|---|---|
| Hide a spam/abusive issue from the page | Add label `hidden` on the GitHub issue. The Worker filters it out of `GET /issues`. |
| Pin an important issue | Add label `pinned`. The page sorts pinned issues to the top. |
| Mark resolved | Close the issue. Page status flips to `resolved`. |
| Mark answered | Comment on the issue as `LeRaffl`. Page derives `answered` status automatically. |
| Wipe the cache so a change shows up faster | Trigger any new POST `/issues` or wait 60 s for the worker cache to expire. |

## 8.7 Bulk re-render

After a refactor that affects rendering for all countries (e.g. plot style change), you need to re-render every country. Two approaches:

### Locally (fastest)
```bash
for c in data/*.csv; do
  name=$(basename "$c" .csv)
  Rscript R/render_country.R "$name"
done
git add images/ params.csv weights.csv posts/
git commit -m "chore: bulk re-render after <reason>"
git push
```

### Via CI (if you want CI to be the source of truth)
```bash
for c in Germany Austria France ...; do
  gh workflow run render-country.yml -f country="$c" -f variant=Whole
  sleep 60   # let each run finish to avoid concurrency throttling
done
```

CI is slower (~30–120 s × 43 countries) but produces deterministic byte-output regardless of which Mac the maintainer happens to be on.

## 8.8 Debugging

### Worker isn't responding

1. Cloudflare dashboard → Workers → `leraffl-gallery-feedback` → Logs (tail)
2. Reproduce the failing request from the page
3. Look for `console.error` lines — typical issues:
   - `Branch create failed: 403 ...` → PAT missing Contents/Pulls scope. Re-extend (§ 8.4).
   - `Failed to read data/<Country>.csv` → file doesn't exist on master yet. Either add the CSV first or wait for the submitter to be more patient.
   - `Too many submissions` → working as intended, KV rate-limit fired.

### Render Action failing

1. Open the failed run in the Actions tab.
2. Common failures:
   - **`missing data file: data/<Country>.csv`** → the country isn't in the repo. Add it via § 8.3.
   - **`no rows for variant 'X' in data/<Country>.csv`** → variant not present in the CSV. Either submit data for it or change the variant input.
   - **`Failed to install package 'showtext'` or similar** → CI cache miss + apt prebuild missing. Re-run; usually transient.
   - **`Error in optim(...)`** → degenerate input (all-zero column, single data point). Check the CSV for the period range.

### Indonesia v1=0 corruption

#### Symptom

The Durations table on the page shows Indonesia's 20→80 transition as ~5 years (sometimes also Custom-pct or "Numerical speed" looking nonsensical) although a fresh R render via § 8.2 produces a 20→80 of ~2 years. Re-running § 8.2 for Indonesia "fixes" it for a while, then the bad values come back after some unrelated country has been rendered.

#### Root cause

1. The R fit (`R/fit.R::fit_history`) is mathematically stable for Indonesia. With current data it converges to `v1 = -6.114813777364e-20, v2 = 15.1628, t0 = 2009`. The 20→80 derived from these is ~2.25 years — correct.
2. `R/upsert.R::upsert_params` writes `v1` to `params.csv` in scientific notation (`-6.114813777364e-20`). Standard R `read.csv` / `write.csv` round-trips this losslessly.
3. The maintainer's **legacy local "auto-publish model" R script** (off-repo, runs from RStudio on the Mac, generates commits like `China: auto-publish model`) reads `params.csv` with code closer to `round(scale, 6)` / default `format()`. Both of those collapse anything below ~1e-7 to literal `0`. The script then writes the whole CSV back, so Indonesia's row goes from `…,-6.114813777364e-20,…` to `…,0,…` (sometimes `-0`).
4. The page used to patch `v1 = 0 → -1e-24` inside `inv_x_years` so the math wouldn't divide by zero. With Indonesia's `v2 ≈ 15`, that constant pushes the entire Weibull ~20 years into the future: 20 % is reached around 2042, 80 % around 2047 → reported 20→80 ≈ 4.9 years. Other countries fit to smaller `v2` (≤ 7) and weren't visibly affected by the same constant.
5. Re-running § 8.2 for Indonesia restores the precision, so the value flips back. Until the next time the legacy script touches `params.csv`.

Confirmed in Git history: alternating commits like `chore: render Indonesia (Whole)` → tiny non-zero `v1`, followed by `China: auto-publish model` → `v1=0`, throughout May 2026.

#### Defence in depth

Two layers, both kept on purpose so either alone covers the bug while we keep the legacy script around:

| Layer | File / function | What it does |
|---|---|---|
| **Frontend** | `index.html::recoverV1FromAnchor()` + `applyV1Recovery()` | At every CSV load (Thresholds, Durations, Builder, World Map, Fleet) every row with `v1 = 0` is rewritten on the fly. The Weibull is anchored at a v2-dependent BEV share at `data_per`: 28 % for `v2 ≥ 10` (the fast-adopter corruption pattern, calibrated against Indonesia's live fit), 50 % otherwise. The reported 20→80 duration lands within ~1 day of the truth for Indonesia and stays bounded for the hypothetical case of a future v2≥10 country whose data_per sits earlier in its rising flank (~40 days worst case). Page never reports the 4.9-year garbage value again, even if `params.csv` was just clobbered. |
| **Backend** | `R/upsert.R::heal_v1_zero_rows()`, invoked from `R/render_country.R` | At the end of every CI render (regardless of which country was the trigger), scan `params.csv` for the corruption fingerprint (`abs(v1) < 1e-25` AND `v2 ≥ 10`). For each hit, re-fit from `data/<Country>.csv` and rewrite the row. Cheap when nothing is wrong; fully autonomous when something is. Means the very next CI render after a clobbered commit cleans the file. |

Both layers stay in place on purpose:
- The **backend self-heal** is the canonical fix — once it runs, params.csv carries the correct tiny-negative `v1` again. Schema unchanged.
- The **frontend anchor recovery** is the user-facing safety net — it kicks in for the window between a corrupting local push and the next CI render touching the repo. The page never shows the garbage 4.9-year number to a visitor in that window.
- Why no `bev_at_data_per` column? Considered and dropped: an explicit anchor column would give < 1 day accuracy unconditionally, but it would extend the public schema. External tools that don't know the new column would silently drop it on round-trip, costing accuracy for any row they touch. Keeping the recovery purely code-side means no external tool can accidentally undo it. The 28 %-anchor heuristic plus the backend self-heal already deliver the same user-visible accuracy in steady state.

If you ever need to manually verify the heal works:

```bash
# Simulate corruption + run heal in isolation:
sed -i.bak 's|^Indonesia,Whole,-[^,]*,|Indonesia,Whole,0,|' params.csv
Rscript -e 'source("R/data.R"); source("R/fit.R"); source("R/upsert.R"); heal_v1_zero_rows()'
grep '^Indonesia' params.csv     # should show -6.114e-20 again
mv params.csv.bak params.csv     # roll back the simulated corruption
```

#### When the legacy script eventually retires

Once the off-repo "auto-publish model" workflow is gone, the corruption source disappears. The recovery code can stay — it costs nothing on clean files and protects against any future tool that does the same thing. Removing it would only be safe if `params.csv` were strictly write-only-by-CI, which is a stronger guarantee than the project currently has.

### Site shows stale data after a render

1. Was the Render Action's commit pushed? `gh run view <id>` should show `chore: render <Country> ...` as the last commit.
2. Did the Build-manifest action run after? Check Actions tab.
3. Did Pages deploy? Settings → Pages → Recent deployments.
4. Hard-refresh the page (`Cmd+Shift+R`) to bypass browser cache.

### Submit form is showing all 14 fuel categories instead of the country's actual subset

The page's CSV-fetch fallback kicked in. Either:
- The branch with the country's CSV isn't merged yet (check master)
- raw.githubusercontent.com had a transient 5xx (rare)

## 8.9 Snapshot Builder curves

The Builder-tab aggregated curves are dumped to `builder_history/<date>.csv` automatically on the 25th of each month (cron in [`snapshot-builder.yml`](../../.github/workflows/snapshot-builder.yml)). The script is [scripts/snapshot_builder.py](../../scripts/snapshot_builder.py); full design notes are in [Flow L](05-flows.md#flow-l--snapshot-builder).

**Trigger manually (e.g. after a large `params.csv` correction):** Actions tab → "Snapshot Builder curves" → Run workflow. Optional `date` input lets you label a back-dated run.

**Run locally to inspect or debug:**

```bash
python scripts/snapshot_builder.py                  # uses today's date
python scripts/snapshot_builder.py --date 2026-05-20
```

The script is zero-dependency (stdlib only) so no `pip install` is needed.

**If a snapshot looks wrong:** the most likely culprit is `params.csv` or `weights.csv` having a row that the in-page Builder also misrenders. Validate by selecting "World" on the Builder tab in the browser and comparing the curve to the snapshot's `world` rows — if they disagree, the script has drifted from the page and the JS/Python parity has a bug; if they agree, the upstream data is the issue.

---

## 8.10 Restoring from disaster

| Disaster | Recovery |
|---|---|
| Repo deleted / corrupted | Restore from any clone — every artefact is in Git |
| Cloudflare account lost | Re-create Worker via wrangler, re-set secret, re-bind KV. The KV's rate-limit data is lost but uncritical. |
| Maintainer's Mac lost | Clone the repo on a new machine, `wrangler login`, `gitcreds_set` for git OAuth, done. The local R scripts (`bev_share_*.R`) are off-repo and need to be restored from iCloud or a backup; if not, the in-repo `R/` pipeline alone is sufficient. |
| GitHub down | Read-side serves from GitHub Pages CDN, may stay up briefly. Submit/feedback writes fail — Worker returns 502; page shows error. Wait for GitHub. |

## See also

- [02-components.md](02-components.md) — what each component does
- [04-interfaces.md](04-interfaces.md) — request/response shapes for the Worker
- [07-secrets-trust.md](07-secrets-trust.md) — what each token can do
