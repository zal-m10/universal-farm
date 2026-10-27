#!/usr/bin/env python3
"""gonka_farm_email.py — Farm GonkaRouter API keys via EMAIL + OTP (no wallet).

Replaces the dead wallet-SIWE signup path (server now answers
wallet_signup_disabled for new wallet signups) with the email path that
was proven end-to-end on the web on 2026-10-25: email -> OTP code ->
verify -> signed in with a 10M-token promo balance and an auto-minted
API key on the dashboard.

Endpoints (mapped from gonkarouter.io public JS bundles, 2026-10-25):
  POST {API}/auth/email/send   {email, channel:"gonka", turnstile_token}
                                 -> {resend_after} (Turnstile REQUIRED)
  POST {API}/auth/email/verify {email, channel:"gonka", code}
                                 -> {token (JWT), user}
  GET  {API}/api/keys          Bearer JWT -> {items:[{id, key_preview}]}
  POST {API}/api/keys/{id}/reveal Bearer JWT -> {key}
  GET  {API}/v1/models        Bearer API key -> 200 (verification)

Mailbox: the user's own Tempik instance (reclaimable inbox by local-part).
Turnstile: solved via Capsolver (public AntiTurnstileTaskProxyLess API);
sitekey taken from gonkarouter.io public runtime config.

Usage:
  python3 gonka_farm_email.py --count 1 [--delay S] [--proxy URL]
      [--tempik-url URL] [--domain DOMAIN] [--out FILE]

Output:  /root/gonka_email_test.txt  (email|user_id|ok|api_key)
Progress:/root/gonka_email_progress.txt (no secrets are ever logged)

Dependencies: requests (stdlib otherwise). No wallet libraries needed.
"""

import argparse
import datetime
import json
import random
import re
import secrets
import string
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

API = "https://api.gonkarouter.io"
WEB = "https://gonkarouter.io"
CHANNEL = "gonka"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Turnstile sitekey from gonkarouter.io public runtime config (__NUXT__).
TURNSTILE_SITEKEY = "0x4AAAAAAFcbQ4RGI69Sc6pz"
TURNSTILE_URL = "https://gonkarouter.io/"
CAPSOLVER_API = "https://api.capsolver.com"

DEFAULT_TEMPIK_URL = "https://tempik.anu.free-account.my.id"
DEFAULT_DOMAIN = "anu.free-account.my.id"
DEFAULT_OUT = Path("/root/gonka_email_test.txt")
DEFAULT_PROGRESS = Path("/root/gonka_email_progress.txt")


def log(msg, progress_file):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(progress_file, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_capsolver_key():
    here = Path(__file__).resolve().parent
    for p in [here / ".capsolver_key",
              Path("/root/universal-farm/tools/.capsolver_key")]:
        try:
            if p.exists():
                key = p.read_text().strip()
                if key:
                    return key
        except OSError:
            continue
    return None


def load_proxies():
    for p in [Path("/root/universal-farm/tools/proxies.txt"),
              Path("tools/proxies.txt")]:
        try:
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
        except OSError:
            continue
    return []


def solve_turnstile(client_key, log_fn, timeout=120):
    """Solve the GonkaRouter Turnstile via Capsolver. Token or None."""
    try:
        r = requests.post(
            f"{CAPSOLVER_API}/createTask",
            json={"clientKey": client_key,
                  "task": {"type": "AntiTurnstileTaskProxyLess",
                           "websiteURL": TURNSTILE_URL,
                           "websiteKey": TURNSTILE_SITEKEY}},
            timeout=15)
        data = r.json()
    except Exception as e:
        log_fn(f"  capsolver createTask error: {e}")
        return None
    if data.get("errorId") != 0:
        log_fn(f"  capsolver createTask error: "
               f"{data.get('errorDescription', data)}")
        return None
    task_id = data["taskId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        try:
            r = requests.post(
                f"{CAPSOLVER_API}/getTaskResult",
                json={"clientKey": client_key, "taskId": task_id},
                timeout=10)
            data = r.json()
        except Exception as e:
            log_fn(f"  capsolver poll error: {e}")
            return None
        if data.get("status") == "ready":
            return data["solution"]["token"]
        if data.get("errorId") != 0:
            log_fn(f"  capsolver error: {data.get('errorDescription', data)}")
            return None
    log_fn("  capsolver: timeout waiting for Turnstile solution")
    return None


class Tempik:
    """Minimal client for the user's own Tempik instance."""

    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/json"})
        self.session_id = None

    def _headers(self):
        if not self.session_id:
            r = self.s.get(f"{self.base}/api/session", timeout=30)
            r.raise_for_status()
            self.session_id = r.json()["sessionId"]
        return {"x-session-id": self.session_id}

    def domains(self):
        try:
            r = self.s.get(f"{self.base}/api/config", timeout=30)
            r.raise_for_status()
            return r.json().get("mailDomains", [])
        except Exception:
            return []

    def create_inbox(self, local_part, domain):
        r = self.s.post(
            f"{self.base}/api/inboxes",
            headers=self._headers(),
            json={"localPart": local_part, "domain": domain},
            timeout=30)
        r.raise_for_status()
        body = r.json()
        addr = body.get("address") or body.get("email") or ""
        if not addr:
            # Fall back to the requested local-part + domain.
            addr = f"{local_part}@{domain}"
        return addr

    def get_messages(self, address):
        r = self.s.get(
            f"{self.base}/api/inboxes/{address}/messages",
            headers=self._headers(),
            timeout=30)
        r.raise_for_status()
        body = r.json()
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("messages", "items", "data"):
                if isinstance(body.get(key), list):
                    return body[key]
        return []

    def wait_for_otp(self, address, log_fn, timeout=150, interval=5):
        """Poll inbox for a 6-digit OTP. Returns code or None.

        The code value is returned to the caller but never logged.
        """
        deadline = time.time() + timeout
        seen = 0
        while time.time() < deadline:
            try:
                msgs = self.get_messages(address)
            except Exception as e:
                log_fn(f"  tempik poll error: {e}")
                time.sleep(interval)
                continue
            if len(msgs) > seen:
                # Only inspect messages we have not seen yet.
                for m in msgs[seen:]:
                    blob = json.dumps(m, ensure_ascii=False)
                    sender = (m.get("from") or m.get("sender") or
                              m.get("fromAddress") or "")
                    codes = re.findall(r"\b(\d{6})\b", blob)
                    if codes and ("gonka" in blob.lower()
                                 or "gonka" in str(sender).lower()):
                        return codes[0]
                    if codes and not seen:
                        return codes[0]
                seen = len(msgs)
            time.sleep(interval)
        return None


def farm_one(session, idx, capsolver_key, tempik, domain, log_fn):
    # 1. Fresh Tempik inbox with a random local-part.
    rand = "".join(secrets.choice(string.ascii_lowercase + string.digits)
                   for _ in range(10))
    local_part = f"gk{rand}"
    try:
        email = tempik.create_inbox(local_part, domain)
    except Exception as e:
        log_fn(f"  tempik create inbox error: {e}")
        return None
    log_fn(f"=== account #{idx} : {email} ===")

    # 2. Solve Turnstile (required by /auth/email/send).
    ts_token = solve_turnstile(capsolver_key, log_fn)
    if not ts_token:
        log_fn("  turnstile solve failed")
        return None

    # 3. Request OTP.
    try:
        r = session.post(
            f"{API}/auth/email/send",
            json={"email": email, "channel": CHANNEL,
                  "turnstile_token": ts_token},
            timeout=60)
    except Exception as e:
        log_fn(f"  email/send error: {e}")
        return None
    if r.status_code != 200:
        log_fn(f"  email/send failed: {r.status_code} {r.text[:200]}")
        return None
    try:
        resend_after = r.json().get("resend_after")
    except Exception:
        resend_after = None
    log_fn(f"  OTP requested (resend_after={resend_after})")

    # 4. Read OTP from Tempik (value never logged).
    code = tempik.wait_for_otp(email, log_fn)
    if not code:
        log_fn("  OTP not received in inbox within timeout")
        return None
    log_fn("  OTP received (6 digits)")

    # 5. Verify OTP -> JWT.
    try:
        r = session.post(
            f"{API}/auth/email/verify",
            json={"email": email, "channel": CHANNEL, "code": code},
            timeout=60)
    except Exception as e:
        log_fn(f"  email/verify error: {e}")
        return None
    if r.status_code != 200:
        log_fn(f"  email/verify failed: {r.status_code} {r.text[:200]}")
        return None
    body = r.json()
    token = body.get("token")
    user_id = (body.get("user") or {}).get("id")
    if not token:
        log_fn("  email/verify: no token returned")
        return None
    log_fn(f"  verified, user_id={user_id}")

    auth_h = {"Authorization": f"Bearer {token}",
              "Origin": WEB, "Referer": f"{WEB}/dashboard"}

    # 6. List keys (auto-minted first item).
    key_id = None
    for _ in range(5):
        try:
            r = session.get(f"{API}/api/keys", headers=auth_h, timeout=60)
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    key_id = items[0]["id"]
                break
            log_fn(f"  list keys: {r.status_code} {r.text[:120]}")
        except Exception as e:
            log_fn(f"  list keys error: {e}")
        time.sleep(5)
    if not key_id:
        log_fn("  no auto-minted key found on this account")
        return None

    # 7. Reveal full key.
    full_key = None
    for _ in range(5):
        try:
            r = session.post(f"{API}/api/keys/{key_id}/reveal",
                             headers=auth_h, timeout=60)
            if r.status_code == 200:
                full_key = r.json().get("key")
                break
            log_fn(f"  reveal: {r.status_code} {r.text[:120]}")
        except Exception as e:
            log_fn(f"  reveal error: {e}")
        time.sleep(5)
    if not full_key:
        log_fn("  reveal failed: no API key")
        return None

    # 8. Verify key via /v1/models.
    try:
        r = session.get(f"{API}/v1/models",
                        headers={"Authorization": f"Bearer {full_key}"},
                        timeout=60)
        if r.status_code != 200:
            log_fn(f"  verify failed ({r.status_code})")
            return None
    except Exception as e:
        log_fn(f"  verify error: {e}")
        return None

    log_fn("  KEY verified via /v1/models 200 OK")
    return {"email": email, "user_id": user_id,
            "api_key": full_key, "ok": True}


def save_key(rec, out_file):
    line = f"{rec['email']}|{rec['user_id']}|ok|{rec['api_key']}\n"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "a") as f:
        f.write(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds between accounts")
    ap.add_argument("--proxy", default=None,
                    help="http://user:pass@host:port (overrides file)")
    ap.add_argument("--tempik-url", default=DEFAULT_TEMPIK_URL)
    ap.add_argument("--domain", default=None,
                    help="Tempik domain (default: anu.free-account.my.id)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--progress", default=str(DEFAULT_PROGRESS))
    args = ap.parse_args()

    progress_file = Path(args.progress)
    log_fn = lambda m: log(m, progress_file)  # noqa: E731

    capsolver_key = load_capsolver_key()
    if not capsolver_key:
        log_fn("ERROR: no Capsolver key found (email send needs Turnstile).")
        sys.exit(1)
    log_fn("capsolver key loaded")

    tempik = Tempik(args.tempik_url)
    domain = args.domain
    if not domain:
        avail = tempik.domains()
        if DEFAULT_DOMAIN in avail:
            domain = DEFAULT_DOMAIN
        elif avail:
            domain = avail[0]
        else:
            domain = DEFAULT_DOMAIN
    log_fn(f"tempik: {args.tempik_url} domain={domain}")

    proxies = [args.proxy] if args.proxy else load_proxies()
    if proxies:
        log_fn(f"proxies loaded: {len(proxies)}")
    else:
        log_fn("WARNING: no proxy — running direct")

    out_file = Path(args.out)
    ok = fail = 0
    for i in range(1, args.count + 1):
        proxy = random.choice(proxies) if proxies else None
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": WEB,
            "Referer": f"{WEB}/",
        })
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        try:
            rec = farm_one(s, i, capsolver_key, tempik, domain, log_fn)
        except Exception as e:
            log_fn(f"  unexpected: {e}")
            rec = None
        if rec:
            save_key(rec, out_file)
            ok += 1
        else:
            fail += 1
        if i < args.count:
            time.sleep(args.delay)

    log_fn(f"=== DONE: {ok}/{args.count} success, {fail} failed ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
