"""Batch runner for the Nscale farm (called by the TUI Run farm menu).

Runs nscale_farm.py once per account index, sequentially, with the
proven Chrome setup: real Google Chrome, headed under xvfb, fresh
visitorId per account (route patch ON), no stealth script. Accounts already present in
nscale_accounts.json are skipped. Prints one RESULT line per account
plus a batch summary at the end; the TUI background mode captures
this output to a log file.

Usage: python batch_farm.py --indices 2,3,4 [--delay 10]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FARM_SCRIPT = HERE / "nscale_farm.py"


def _base_dir() -> Path:
    return Path(os.environ.get("NSCALE_DIR", str(Path.home() / "nscale-farm")))


def _done_emails() -> set[str]:
    out = _base_dir() / "nscale_accounts.json"
    if not out.exists():
        return set()
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {str(d.get("email", "")).strip().lower() for d in data if isinstance(d, dict)}


def _accounts() -> list[tuple[str, str]]:
    path = Path(os.environ.get("NSCALE_ACCOUNTS_FILE", str(_base_dir() / "accounts.txt")))
    if not path.exists():
        return []
    accounts: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        email, password = line.split(":", 1)
        email, password = email.strip().lower(), password.strip()
        if email and password:
            accounts.append((email, password))
    return accounts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", required=True, help="comma-separated 1-based account indices")
    ap.add_argument("--delay", type=int, default=10, help="seconds between accounts")
    args = ap.parse_args()
    try:
        indices = [int(x) for x in args.indices.split(",") if x.strip()]
    except ValueError:
        print("RESULT: FAIL bad indices", flush=True)
        return 2
    accounts = _accounts()
    if not accounts:
        print("RESULT: FAIL no accounts file", flush=True)
        return 2
    done = _done_emails()
    venv_python = Path(sys.executable)
    passed = failed = skipped = 0
    failed_idx: list[int] = []
    for pos, idx in enumerate(indices):
        if idx < 1 or idx > len(accounts):
            print(f"RESULT: FAIL index {idx} out of range", flush=True)
            failed += 1
            failed_idx.append(idx)
            continue
        email = accounts[idx - 1][0]
        if email in done:
            print(f"RESULT: SKIP {idx} {email} already done", flush=True)
            skipped += 1
            continue
        if pos > 0 and args.delay > 0:
            time.sleep(args.delay)
        env = dict(os.environ)
        env["NSCALE_BROWSER"] = "chrome"
        env["NSCALE_ROUTE"] = "1"
        env["NSCALE_STEALTH"] = "0"
        env["NSCALE_HEADLESS"] = "0"
        env["NSCALE_DIR"] = str(_base_dir())
        cmd = [str(venv_python), str(FARM_SCRIPT), str(idx)]
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a"] + cmd
        print(f"BATCH: running index {idx} ({email})", flush=True)
        try:
            rc = subprocess.run(cmd, env=env).returncode
        except Exception as exc:
            print(f"RESULT: FAIL {idx} {type(exc).__name__}", flush=True)
            failed += 1
            failed_idx.append(idx)
            continue
        if rc == 0:
            passed += 1
            done = _done_emails()
        else:
            failed += 1
            failed_idx.append(idx)
    print(f"BATCH SUMMARY: pass={passed} fail={failed} skip={skipped} failed_indices={failed_idx}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
