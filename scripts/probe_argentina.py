#!/usr/bin/env python3
"""TEMPORARY probe v4: prove the live fetch path reproduces the committed
data/Argentina*.csv byte-for-byte. Delete when done."""
import subprocess, sys

def run(cmd):
    print("\n$ " + cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    print(r.stdout[-6000:], r.stderr[-3000:], flush=True)
    return r

run("python scripts/test_fetch_argentina.py")
run("python scripts/fetch_argentina.py --period 2026-08")            # throttle: no HTTP
run("python scripts/fetch_argentina.py --period 2026-08 --force")    # live, 2025+2026 zips
print("DIFF-MONTHLY:", run("git status --porcelain data/ && git diff --stat data/").stdout or "clean")
run("python scripts/fetch_argentina.py --backfill --force")          # live, 2018→2026
print("DIFF-BACKFILL:", run("git status --porcelain data/ && git diff --stat data/").stdout or "clean")
run("git diff data/ | head -60")
sys.exit(0)
