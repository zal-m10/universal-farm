"""Nscale farm: Google SSO -> Workspace ToS -> onboarding -> $5 credit -> service token.

Proven live (2026-10-30): Playwright Chromium is rejected by Nscale
onboarding with 403 Access denied, while real Google Chrome passes
(onboarding 200, credit 5.0, token captured). So this script MUST run
with NSCALE_BROWSER=chrome, headed under xvfb, with NSCALE_ROUTE=1
(fresh visitorId per account, otherwise the second account fails
with 409 Signup already exists) and NSCALE_STEALTH=0 (no stealth
init script). The TUI Run farm sets exactly those env vars.

Accounts come from accounts.txt in the base dir (NSCALE_DIR, default
~/nscale-farm): one "email:password" per line. Results go to
nscale_accounts.json in the same dir (mode 600, token values included
— keep that file private).

Run: python nscale_farm.py <account_index> [org_name]
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright



# --- Linux port: base dir + accounts loader (replaces deepgram_signup) ---
def _base_dir():
    """Base dir for output, profiles and accounts.txt.

    Override with NSCALE_DIR. Default: ~/nscale-farm (for root on a
    server this is /root/nscale-farm, matching older installs).
    """
    return Path(os.environ.get("NSCALE_DIR", str(Path.home() / "nscale-farm")))


def load_accounts(path=None):
    """Read accounts.txt: one 'email:password' per line.

    Blank lines and lines starting with '#' are skipped. The password is
    split on the FIRST ':' only, so a password containing ':' still works.
    Override the file with NSCALE_ACCOUNTS_FILE.
    """
    p = Path(path) if path else Path(
        os.environ.get("NSCALE_ACCOUNTS_FILE", str(_base_dir() / "accounts.txt"))
    )
    if not p.exists():
        raise FileNotFoundError(f"accounts file not found: {p} (copy accounts.txt.example to accounts.txt and fill it in on the server)")
    accounts = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        email, password = line.split(":", 1)
        email, password = email.strip(), password.strip()
        if email and password:
            accounts.append((email, password))
    return accounts


def accounts():
    return load_accounts()


def _headless():
    """Headless by default on a server (no display). NSCALE_HEADLESS=0 to show the browser."""
    return os.environ.get("NSCALE_HEADLESS", "1") != "0"


def _browser_args():
    return ["--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage"]


def _proxy():
    """Proxy from NSCALE_PROXY, in the farm proxies.txt format user:pass@host:port.

    Returns a Playwright proxy dict, or None when unset. The value itself is
    never printed; only whether a proxy is in use is logged by the caller.
    """
    raw = os.environ.get("NSCALE_PROXY", "").strip()
    if not raw:
        return None
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    auth, _, hostport = raw.rpartition("@")
    server = "http://" + hostport
    if auth and ":" in auth:
        user, _, pw = auth.partition(":")
        return {"server": server, "username": user, "password": pw}
    return {"server": server}

BASE = "https://console.nscale.com"
OUT = _base_dir() / "nscale_accounts.json"
SEL_EMAIL = "#identifierId"
SEL_PWD = 'input[type=password][name="Passwd"]'

JS_TICK = """() => {
    let n = 0;
    for (const b of document.querySelectorAll('button[role=checkbox],[role=checkbox]')) {
        if (!b.offsetWidth) continue;
        const on = b.getAttribute('aria-checked') === 'true' || b.checked === true;
        if (!on) { b.click(); n++; }
    }
    return n;
}"""
JS_CLICK = """(p) => {
    const re = new RegExp(p, 'i');
    const els = [...document.querySelectorAll('button,div[role=button],a[role=button],input[type=submit]')];
    const b = els.find(e => re.test((e.innerText || e.value || '').trim()) && e.offsetWidth && !e.disabled);
    if (!b) return false; b.click(); return true;
}"""


STEALTH_JS = """() => {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    window.chrome = {runtime: {}};
}"""


def click_text(page, pattern) -> bool:
    for f in page.frames:
        try:
            if f.evaluate(JS_CLICK, pattern):
                return True
        except Exception:
            return False
    return False


def save(rec: dict) -> None:
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    data = [d for d in data if d.get("email") != rec["email"]]
    data.append(rec)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(OUT, 0o600)
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python ns_full.py <account_index> [org_name]")
        return 2
    idx = int(sys.argv[1])
    org_name = sys.argv[2] if len(sys.argv) > 2 else f"org{idx}-{secrets.token_hex(2)}"
    _accs = load_accounts()
    if idx < 1 or idx > len(_accs):
        print(f"RESULT: FAIL account index {idx} out of range (1..{len(_accs)})")
        return 2
    email, password = _accs[idx - 1]
    prof = str(_base_dir() / "profiles" / f"p3-{idx}-{int(time.time())}")
    shutil.rmtree(prof, ignore_errors=True)
    print("account:", email, "org:", org_name, flush=True)

    tokens: list[str] = []
    create_body: list[str] = []

    proxy = _proxy()
    browser_name = os.environ.get("NSCALE_BROWSER", "chromium").strip().lower()
    print("proxy:", "ON" if proxy else "OFF", "browser:", browser_name, flush=True)
    with sync_playwright() as pw:
        engine = pw.firefox if browser_name == "firefox" else pw.chromium
        ua = ("Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
              if browser_name == "firefox" else
              "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
        kwargs = dict(headless=_headless(), viewport={"width": 1400, "height": 950},
                      proxy=proxy, user_agent=ua)
        if browser_name == "firefox":
            kwargs["args"] = []
        else:
            kwargs["args"] = _browser_args()
            if browser_name == "chrome":
                kwargs["channel"] = "chrome"
        ctx = engine.launch_persistent_context(prof, **kwargs)
        # NSCALE_STEALTH=0: skip the stealth init script. Its fake
        # navigator.plugins / languages / window.chrome values can
        # themselves be fingerprinted as inconsistent by Kasada.
        if os.environ.get("NSCALE_STEALTH", "1") != "0":
            try:
                ctx.add_init_script(STEALTH_JS)
            except Exception:
                pass
        ctx.clear_cookies()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def patch_visitor(route):
            try:
                body = json.loads(route.request.post_data or "{}")
            except Exception:
                body = {}
            # NSCALE_PATCH_VISITOR=0: send the browser's real visitorId
            # unchanged. Manual phone onboarding (which works) uses the real
            # Kasada visitorId; the random-hex replacement is the prime
            # suspect for the script's consistent 403 Access denied.
            if os.environ.get("NSCALE_PATCH_VISITOR", "1") != "0" and "visitorId" in body:
                body["visitorId"] = secrets.token_hex(16)   # fresh 32-hex per attempt
            create_body.append(json.dumps(body))
            print("SEND onboarding:", json.dumps(body)[:160], flush=True)
            route.continue_(post_data=json.dumps(body))

        # NSCALE_ROUTE=0: do not intercept the onboarding request at all,
        # so the browser sends its original body untouched. Even a
        # no-change re-send re-serialises the JSON, which could break a
        # request signature tied to the original body.
        if os.environ.get("NSCALE_ROUTE", "1") != "0":
            page.route("**/api/auth/onboarding", patch_visitor)

        def on_resp(r):
            if r.url.endswith("/api/auth/onboarding"):
                try:
                    b = r.text()[:300]
                except Exception:
                    b = ""
                print(f"ONBOARDING {r.status} :: {b}", flush=True)
            if r.request.method != "GET" and "nscale" in r.url:
                try:
                    t = r.text()
                except Exception:
                    return
                for m in re.findall(r"eyJ[A-Za-z0-9._-]{80,}", t):
                    if m not in tokens:
                        tokens.append(m)
                        print("TOKEN_CAPTURED len=", len(m), flush=True)

        page.on("response", on_resp)

        # login
        page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)
        page.locator('button[data-provider="google"]').first.click()
        page.wait_for_timeout(4000)
        if "accountchooser" in page.url:
            click_text(page, r"(Use another account|Gunakan akun lain)")
            page.wait_for_timeout(3000)
        if page.locator(SEL_EMAIL).count():
            page.click(SEL_EMAIL)
            page.keyboard.type(email, delay=40)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)

        pwd_done = 0
        for _ in range(45):
            if "console.nscale.com" in page.url:
                break
            if "accounts.google.com" not in page.url and "google.co.id" not in page.url:
                page.wait_for_timeout(1500)
                continue
            box = page.locator(SEL_PWD).first
            try:
                need = box.count() and box.is_visible()
            except Exception:
                need = False
            if need and pwd_done < 2:
                box.click()
                page.keyboard.type(password, delay=40)
                page.keyboard.press("Enter")
                pwd_done += 1
                page.wait_for_timeout(4000)
                continue
            if need:
                page.wait_for_timeout(1500)
                continue
            try:
                page.evaluate(JS_TICK)
            except Exception:
                pass
            click_text(page, r"^(Continue|Allow|Izinkan|Lanjutkan|Accept|Agree|I agree|Saya setuju|Setuju|Mengerti|I understand|Got it)$")
            page.wait_for_timeout(1800)

        # Linux port: Workspace for Education accounts land on a Terms of
        # Service speedbump after the password step. Accept it explicitly
        # instead of waiting for the generic loop to stumble onto it.
        for _ in range(10):
            if "workspacetermsofservice" not in page.url:
                break
            try:
                page.evaluate(JS_TICK)
            except Exception:
                pass
            hit = click_text(page, r"(Accept|I agree|Agree|Saya setuju|Setuju|Mengerti|I understand|Got it|Continue|Lanjutkan)")
            print("tos accept clicked:", hit, flush=True)
            page.wait_for_timeout(3000)

        for _ in range(12):
            if "console.nscale.com" in page.url and ("/auth/onboarding" in page.url
                                                     or "/organization/" in page.url
                                                     or "/auth/error" in page.url):
                break
            page.wait_for_timeout(2000)
        print("landed:", page.url[:110], flush=True)
        own = re.search(r"/organization/([0-9a-f-]{36})", page.url)
        if own:
            try:
                rr = page.request.get(f"{BASE}/api/organization/{own.group(1)}/billing/billing-details", timeout=15000)
                owen = (rr.json() or {}).get("email") or ""
                print("org owner:", owen, flush=True)
                if owen and email.lower() not in owen.lower():
                    print("RESULT: FAIL wrong_account (org milik " + owen + ")", flush=True)
                    return 1
            except Exception as exc:  # noqa: BLE001
                print("owner check err:", type(exc).__name__, flush=True)

        if "/auth/error" in page.url:
            print("RESULT: FAIL auth", flush=True)
            return 1

        if "/auth/onboarding" in page.url:
            # Form fix: under a slow proxy the page can be visible before
            # React hydration finishes, so a fast fill+tick updates the DOM
            # but not the app state, leaving the submit button disabled.
            # Wait for hydration, then fill+tick in a loop until the button
            # actually enables (or 3 attempts are spent).
            try:
                page.wait_for_selector("#organization-name", state="visible", timeout=10000)
                page.wait_for_timeout(3000)
                for attempt in range(3):
                    page.click("#organization-name")
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Delete")
                    page.keyboard.type(org_name, delay=80)
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(1500)
                    print("org field:", page.input_value("#organization-name"), flush=True)
                    ticks = page.evaluate(JS_TICK)
                    print("tos ticks:", ticks, flush=True)
                    if not ticks:
                        try:
                            page.locator('button[role=checkbox]').first.click(timeout=5000)
                            print("tos checkbox playwright click", flush=True)
                        except Exception as exc:  # noqa: BLE001
                            print("tos click err:", type(exc).__name__, flush=True)
                    page.wait_for_timeout(2000)
                    st = page.evaluate("""() => {
                        const b = [...document.querySelectorAll('button')].find(e => /create organization/i.test(e.innerText||''));
                        const c = document.querySelector('button[role=checkbox]');
                        return b ? {disabled: b.disabled, label: b.innerText.trim(), checked: c ? c.getAttribute('aria-checked') : null} : null; }""")
                    print("button attempt", attempt, ":", st, flush=True)
                    if st and not st["disabled"]:
                        break
            except Exception as exc:  # noqa: BLE001
                print("org fill err:", type(exc).__name__, flush=True)
            print("submit:", click_text(page, r"^Create Organization$"), flush=True)
            for _ in range(10):
                page.wait_for_timeout(2000)
                if "/organization/" in page.url:
                    break
            print("after submit:", page.url[:110], flush=True)

        # app may bounce through /auth/login?organization=... ; wait for the org page
        for _ in range(12):
            if re.search(r"/organization/[0-9a-f-]{36}", page.url):
                break
            page.wait_for_timeout(3000)
        m = re.search(r"/organization/([0-9a-f-]{36})", page.url)
        if not m:
            try:
                print("text:", " ".join(page.inner_text("body").split())[:200], flush=True)
            except Exception:
                pass
            print("RESULT: FAIL org", flush=True)
            return 1
        org_id = m.group(1)
        print("ORG:", org_id, flush=True)

        # bind session to the new org, then REDEEM the $5 dashboard credit
        credit = None
        try:
            page.goto(f"{BASE}/auth/login?returnTo=%2Forganization%2F{org_id}",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            page.goto(f"{BASE}/organization/{org_id}", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(6000)
            hit = page.evaluate("""() => {
                const b = [...document.querySelectorAll('button,a,[role=button]')]
                    .find(e => /redeem credit/i.test(e.innerText || ''));
                if (!b) return null;
                b.scrollIntoView({block: 'center'});
                const r = b.getBoundingClientRect();
                return {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
            }""")
            if hit:
                page.mouse.click(hit["x"], hit["y"])
                page.wait_for_timeout(5000)
                print("redeem: clicked", flush=True)
            else:
                print("redeem: no banner", flush=True)
            page.goto(f"{BASE}/organization/{org_id}/settings/credit",
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4500)
            m2 = re.search(r"Balance\s*\$([0-9.]+)", " ".join(page.inner_text("body").split()))
            credit = float(m2.group(1)) if m2 else None
            print("credit:", credit, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("credit err:", type(exc).__name__, flush=True)

        page.goto(f"{BASE}/organization/{org_id}/settings/service-tokens",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        tok_name = "svc-" + secrets.token_hex(3)
        try:
            page.get_by_role("button", name="Add Service Token", exact=False).first.click(timeout=8000)
            page.wait_for_timeout(2000)
            inp = page.locator('input[name="name"]').first
            inp.wait_for(state="visible", timeout=8000)
            inp.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.type(tok_name, delay=30)
            page.get_by_role("button", name="Create Service Token", exact=True).first.click(timeout=6000)
            page.wait_for_timeout(10000)
        except Exception as exc:  # noqa: BLE001
            print("token ui err:", type(exc).__name__, flush=True)

        if not tokens:
            found = page.evaluate("""() => {
                for (const e of document.querySelectorAll('input,textarea,code,pre,span,div')) {
                    const v = (e.value || e.innerText || '').trim();
                    if (v && v.length > 200 && /^ey[A-Za-z0-9._-]+$/.test(v)) return v;
                }
                return null; }""")
            if found:
                tokens.append(found)

        if not tokens:
            save({"email": email, "org_id": org_id, "org_name": org_name, "credit_usd": credit,
                  "status": "no_token"})
            print("RESULT: FAIL token", flush=True)
            return 1

        import urllib.request
        def _ok(t):
            try:
                rq = urllib.request.Request("https://inference.api.nscale.com/v1/models",
                                            headers={"Authorization": f"Bearer {t}"})
                with urllib.request.urlopen(rq, timeout=25) as rr:
                    return rr.status == 200
            except Exception:
                return False
        tries = 0
        while tokens and not _ok(tokens[0]) and tries < 2:
            tries += 1
            print(f"token invalid -> recreate #{tries}", flush=True)
            nm = "svc-" + secrets.token_hex(3)
            page.goto(f"{BASE}/organization/{org_id}/settings/service-tokens",
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            try:
                page.get_by_role("button", name="Add Service Token", exact=False).first.click(timeout=8000)
                page.wait_for_timeout(2000)
                inp2 = page.locator('input[name="name"]').first
                inp2.wait_for(state="visible", timeout=8000)
                inp2.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.keyboard.type(nm, delay=30)
                page.get_by_role("button", name="Create Service Token", exact=True).first.click(timeout=6000)
                page.wait_for_timeout(10000)
            except Exception as exc:  # noqa: BLE001
                print("recreate err:", type(exc).__name__, flush=True)
            fresh = [t for t in tokens if _ok(t)]
            if fresh:
                tokens.insert(0, fresh[0])
                break
            newt = page.evaluate("""() => {
                for (const e of document.querySelectorAll('input,textarea,code,pre,span,div')) {
                    const v = (e.value || e.innerText || '').trim();
                    if (v && v.length > 200 && /^eyJhbGciOiJBMjU2R0NNS1ci/.test(v)) return v;
                }
                return null; }""")
            if newt and _ok(newt):
                tokens.insert(0, newt)
                tok_name = nm
                print("recreated valid token", flush=True)
                break
        rec = {"email": email, "org_id": org_id, "org_name": org_name, "credit_usd": credit,
               "base_url": "https://inference.api.nscale.com/v1", "service_token": tokens[0],
               "token_name": tok_name, "status": "ok"}
        save(rec)
        print("RESULT: PASS | credit", credit, "| token len", len(tokens[0]), "| org", org_id, flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
