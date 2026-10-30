#!/usr/bin/env python3
"""Monitor for Nscale background farm: inject to 9Router + Telegram notify.

Same pattern as the other farms' inject monitors: watch the batch PID,
send progress notifications every NOTIFY_CHUNK keys, inject when the
batch finishes (if the Nscale auto-inject toggle is ON), then send the
final completion notification in the TokenHarbor/GonkaRouter format
(account emails + full API keys, via _notify_farm_done).
"""
import sys
import time
import os
import json
from pathlib import Path

# Repo root = 3 levels up from this file: nscale/ -> tools/ -> repo
REPO_DIR = Path(__file__).resolve().parent.parent.parent


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False


def main():
    farm_pid = int(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    before_keys = set(json.loads(sys.argv[3])) if len(sys.argv) > 3 else set()
    print(f"[monitor] Watching Nscale farm PID {farm_pid}...", flush=True)
    sys.path.insert(0, str(REPO_DIR))
    from tools.tokenharbor.farm_tui import (
        _inject_nscale_to_9router, _load_state, _get_nscale_results,
        _notify_farm_done, NOTIFY_CHUNK)
    sent = set()

    def _fresh(keys):
        return [a for a in keys
                if a.get("service_token")
                and a["service_token"] not in before_keys
                and a["service_token"] not in sent]

    def _emails(entries):
        return [a.get("email", "") for a in entries]

    while pid_alive(farm_pid):
        try:
            results = _get_nscale_results()
            fresh = _fresh(results)
            while len(fresh) >= NOTIFY_CHUNK:
                chunk = fresh[:NOTIFY_CHUNK]
                prog = f"{len(sent)+len(chunk)}/{count}" if count else f"{len(sent)+len(chunk)}"
                _notify_farm_done("Nscale", NOTIFY_CHUNK, NOTIFY_CHUNK, 0,
                                  [a["service_token"] for a in chunk],
                                  progress=prog, emails=_emails(chunk))
                sent.update(a["service_token"] for a in chunk)
                fresh = fresh[NOTIFY_CHUNK:]
                print(f"[monitor] Progress sent: {len(sent)} keys.", flush=True)
        except Exception as e:
            print(f"[monitor] Progress check failed: {e}", flush=True)
        time.sleep(20)
    print(f"[monitor] Farm PID {farm_pid} finished.", flush=True)
    state = _load_state()
    if state.get("nscale_auto_inject", False):
        added, skipped, err = _inject_nscale_to_9router()
        print(f"[monitor] Inject: {added} added, {skipped} skipped, err={err}", flush=True)
    try:
        results = _get_nscale_results()
        fresh = _fresh(results)
        total_done = len(sent) + len(fresh)
        failed = max(0, count - total_done) if count else 0
        _notify_farm_done("Nscale", count if count else total_done,
                          total_done, failed,
                          [a["service_token"] for a in fresh],
                          emails=_emails(fresh))
        print("[monitor] Telegram sent.", flush=True)
    except Exception as e:
        print(f"[monitor] Telegram failed: {e}", flush=True)


if __name__ == "__main__":
    main()
