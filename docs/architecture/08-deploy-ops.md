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

### Site shows stale data after a render

1. Was the Render Action's commit pushed? `gh run view <id>` should show `chore: render <Country> ...` as the last commit.
2. Did the Build-manifest action run after? Check Actions tab.
3. Did Pages deploy? Settings → Pages → Recent deployments.
4. Hard-refresh the page (`Cmd+Shift+R`) to bypass browser cache.

### Submit form is showing all 14 fuel categories instead of the country's actual subset

The page's CSV-fetch fallback kicked in. Either:
- The branch with the country's CSV isn't merged yet (check master)
- raw.githubusercontent.com had a transient 5xx (rare)

## 8.9 Restoring from disaster

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
