#!/usr/bin/env python3
"""
gonka_farm.py — Farm GonkaRouter (api.gonkarouter.io) API keys.

Pure HTTP SIWE (Sign-In With Ethereum) — no browser, no email, no captcha.
  GET  /auth/nonce?address=0x...     -> nonce
  POST /auth/login {address, message, signature} -> JWT token
  GET  /api/keys (Bearer JWT)        -> auto-minted key list
  POST /api/keys/{id}/reveal         -> full API key
  GET  /api/me                       -> balance check

Each account gets $20 USDT credit. Each "account" is a fresh Ethereum wallet.

Usage:
  python3 gonka_farm.py --count 5 [--delay S] [--proxy http://user:pass@host:port]

Output: /root/gonka_keys.txt  (address|user_id|ok|api_key)
Progress: /root/gonka_farm_progress.txt

Dependencies: eth-account, requests
"""
import argparse
import datetime
import json
import random
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:
    print("pip install eth-account", file=sys.stderr)
    sys.exit(1)

BASE = "https://api.gonkarouter.io"
WEB = "https://gonkarouter.io"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

KEYS_FILE = Path("/root/gonka_keys.txt")
PROGRESS_FILE = Path("/root/gonka_farm_progress.txt")


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(PROGRESS_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_proxies():
    """Load proxies from the farm proxy file (one per line)."""
    for p in [Path("/root/universal-farm/tools/proxies.txt"),
              Path("/root/harbor-fixed/tools/proxies.txt"),
              Path("tools/proxies.txt")]:
        if p.exists():
            out = []
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    if not re.match(r"^\w+://", line):
                        line = "http://" + line
                    out.append(line)
            if out:
                return out
    return []


def _get_nonce(session, addr):
    """Get a fresh nonce for the address."""
    for attempt in range(3):
        try:
            r = session.get(f"{BASE}/auth/nonce?address={addr}", timeout=30)
            if r.status_code == 200:
                return r.json().get("nonce")
        except Exception as e:
            log(f"  nonce error: {e}")
        time.sleep(5)
    return None


def _sign_siwe(addr, priv, nonce):
    """Build and sign a fresh SIWE message."""
    issued = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")
    message = (
        "gonkarouter.io wants you to sign in with your Ethereum account:\n"
        f"{addr}\n\n"
        f"Sign in to GonkaRouter.\n\n"
        f"URI: https://gonkarouter.io\n"
        f"Version: 1\n"
        f"Chain ID: 1\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued}"
    )
    signable = encode_defunct(text=message)
    sig = Account.sign_message(signable, priv).signature.hex()
    return message, sig


def farm_one(session, idx):
    # 1. Generate fresh wallet
    acct = Account.create()
    addr = acct.address
    priv = acct.key.hex()
    log(f"=== account #{idx} : {addr} ===")

    # 2-4. Nonce + sign + login, with fresh nonce per retry
    # (nonce is single-use; a timed-out attempt may have consumed it)
    token = None
    user_id = None
    for attempt in range(3):
        nonce = _get_nonce(session, addr)
        if not nonce:
            log("  nonce failed")
            continue
        message, sig = _sign_siwe(addr, priv, nonce)
        try:
            r = session.post(
                f"{BASE}/auth/login",
                json={"address": addr, "channel": "gonka",
                      "message": message, "signature": sig},
                timeout=30)
            if r.status_code == 200:
                body = r.json()
                token = body.get("token")
                user_id = body.get("user", {}).get("id")
                break
            log(f"  login attempt {attempt+1}: {r.status_code} {r.text[:80]}")
        except Exception as e:
            log(f"  login error: {e}")
        time.sleep(5)
    if not token:
        log("  login failed")
        return None
    log(f"  logged in, user_id={user_id}")

    auth_h = {"Authorization": f"Bearer {token}",
              "Origin": WEB, "Referer": f"{WEB}/dashboard"}

    # 5. List keys (auto-minted "default")
    key_id = None
    full_key = None
    for attempt in range(5):
        try:
            r = session.get(f"{BASE}/api/keys", headers=auth_h, timeout=30)
            if r.status_code == 200:
                keys = r.json().get("items", [])
                if keys:
                    key_id = keys[0]["id"]
                break
        except Exception as e:
            log(f"  list keys error: {e}")
        time.sleep(5)

    # 6. Reveal full key
    if key_id:
        for attempt in range(5):
            try:
                r = session.post(f"{BASE}/api/keys/{key_id}/reveal",
                                 headers=auth_h, timeout=30)
                if r.status_code == 200:
                    full_key = r.json().get("key")
                    break
            except Exception as e:
                log(f"  reveal error: {e}")
            time.sleep(5)
    if not full_key:
        log("  reveal failed: no API key")
        return None

    # 7. Balance check
    balance = "?"
    try:
        r = session.get(f"{BASE}/api/me",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30)
        if r.status_code == 200:
            bal = r.json().get("balance") or {}
            balance = bal.get("USDT", "?")
            log(f"  balance: ${balance} USDT")
    except Exception as e:
        log(f"  balance check: {e}")

    # 8. Verify via /v1/models
    try:
        r = session.get(f"{BASE}/v1/models",
                        headers={"Authorization": f"Bearer {full_key}"},
                        timeout=30)
        if r.status_code != 200:
            log(f"  verify failed ({r.status_code})")
            return None
    except Exception as e:
        log(f"  verify error: {e}")
        return None

    log(f"  KEY: {full_key[:14]}... OK")
    return {"address": addr, "user_id": user_id,
            "api_key": full_key, "ok": True}


def save_key(rec):
    line = f"{rec['address']}|{rec['user_id']}|ok|{rec['api_key']}\n"
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KEYS_FILE, "a") as f:
        f.write(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds between accounts")
    ap.add_argument("--proxy", default=None,
                    help="http://user:pass@host:port (overrides file)")
    args = ap.parse_args()

    proxies = [args.proxy] if args.proxy else load_proxies()
    if proxies:
        log(f"proxies loaded: {len(proxies)}")
    else:
        log("WARNING: no proxy — running direct")

    ok = fail = 0
    for i in range(1, args.count + 1):
        proxy = random.choice(proxies) if proxies else None
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        try:
            rec = farm_one(s, i)
        except Exception as e:
            log(f"  unexpected: {e}")
            rec = None
        if rec:
            save_key(rec)
            ok += 1
        else:
            fail += 1
        if i < args.count:
            time.sleep(args.delay)

    log(f"=== DONE: {ok}/{args.count} success, {fail} failed ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
