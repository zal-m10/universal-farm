"""Automated TokenHarbor farming using a real Chromium browser (Playwright).

Full-browser pipeline (no HTTP login): disposable email -> browser signup
-> dashboard -> trigger verification email -> verify link (same browser
session) -> enable free models -> create API key in-page -> account dict.

Why full-browser: TokenHarbor's HTTP login path is dead (it depended on a
Supabase legacy key disabled 2026-10-22), while the browser session stays
authenticated via cookies, so key creation can happen with an in-page
fetch to the site's own /api/keys endpoint -- the same call the dashboard
UI itself makes.

Proven site behavior (browser test 2026-10-26): signup has no Turnstile /
CAPTCHA challenge, redirects straight to /dashboard (unverified), and
shows a "Verify your email to make API calls" banner with a "Verify email"
button; the verification email is sent when that button is clicked.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

SIGNUP_URL = "https://tokenharbor.ai/login?mode=signup"
DASHBOARD_URL = "https://tokenharbor.ai/dashboard"

# Minimal stealth: hide the most common automation fingerprints.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
"""


def _proxy_config() -> Optional[dict]:
    """Build Playwright proxy config from environment (VM needs it)."""
    import os
    url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    if not url:
        return None
    return {"server": url}


def _parse_proxy_arg(proxy: Optional[str]) -> Optional[dict]:
    """Parse a proxy string into a Playwright proxy dict.

    Format: [http://|socks5://]user:pass@host:port. None -> env config.
    """
    if not proxy:
        return _proxy_config()
    m = re.match(r"(?:(https?|socks5?)://)?([^:]+):([^@]+)@([^:]+):(\d+)", proxy)
    if m:
        scheme, user, pwd, host, port = m.groups()
        server_scheme = "socks5" if scheme == "socks5" else "http"
        return {"server": f"{server_scheme}://{host}:{port}",
                "username": user, "password": pwd}
    return {"server": proxy}


def _launch_browser(p, headless: bool, proxy: Optional[str]):
    """Launch Chromium with the farm's standard stealth setup."""
    browser = p.chromium.launch(
        headless=headless,
        proxy=_parse_proxy_arg(proxy),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Jakarta",
    )
    ctx.add_init_script(STEALTH_JS)
    return browser, ctx


def _do_signup(page, email: str, password: str,
               timeout_ms: int = 120_000, verbose: bool = True) -> tuple[bool, str]:
    """Fill the signup form and submit. Returns (ok, detail).

    Assumes the page is already open (any login/signup URL state).
    """
    def log(msg: str):
        if verbose:
            print(f"    [browser] {msg}", flush=True)

    log("ensuring Sign up tab is active ...")
    try:
        signup_tab = page.query_selector(
            'button:has-text("Sign up"), [role="tab"]:has-text("Sign up"),'
            ' a:has-text("Sign up")')
        if signup_tab:
            page.evaluate(
                """(el) => {
                    const txt = (el.innerText || '').trim();
                    if (txt.toLowerCase() === 'sign up') el.click();
                }""", signup_tab)
            page.wait_for_timeout(2000)
    except Exception:
        pass
    log("page loaded, waiting for email field ...")
    try:
        page.wait_for_selector('input[type="email"]', timeout=30000)
    except PwTimeout:
        title = page.title()
        body = page.evaluate("() => document.body.innerText.slice(0, 300)") or ""
        return False, f"signup form not loaded (title: {title}) body={body[:150]!r}"
    log("filling credentials ...")
    # Dismiss cookie banner first (may cover form elements).
    try:
        for sel in ['button:has-text("Essential only")',
                    'button:has-text("Accept")',
                    '[aria-label*="cookie" i] button']:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(1000)
                break
    except Exception:
        pass
    page.fill('input[type="email"]', email)
    # Robust password fill with verification.
    page.wait_for_selector('input[type="password"]', timeout=15000)
    page.fill('input[type="password"]', password)
    pw_val = page.evaluate(
        "() => document.querySelector('input[type=\"password\"]').value")
    if not pw_val:
        log("WARNING: password field empty after fill, retrying ...")
        page.evaluate(
            "() => document.querySelector('input[type=\"password\"]').focus()")
        page.keyboard.type(password, delay=50)
        pw_val = page.evaluate(
            "() => document.querySelector('input[type=\"password\"]').value")
    log(f"password filled: {'OK' if pw_val else 'FAILED'}")

    # Turnstile: only wait when a widget is actually present. The current
    # signup flow shows no Turnstile at all, so waiting unconditionally
    # would burn 60s per account for nothing.
    has_widget = page.evaluate(
        """() => {
            return !!(document.querySelector('iframe[src*="turnstile"], iframe[src*="cloudflare"], .cf-turnstile, input[name="cf-turnstile-response"]'));
        }""")
    if has_widget:
        log("turnstile widget present, waiting for auto-verify ...")
        token = None
        deadline = time.time() + 30
        while time.time() < deadline:
            token = page.evaluate(
                """() => {
                    const el = document.querySelector(
                        'input[name="cf-turnstile-response"]');
                    return el && el.value ? el.value : null;
                }"""
            )
            if token:
                break
            time.sleep(1.5)
        log(f"turnstile token: {'OK' if token else 'MISSING (will submit anyway)'}")
    else:
        log("no turnstile widget, submitting directly ...")

    # Submit the form.
    log("submitting ...")
    btn = page.query_selector('button[type="submit"]')
    if btn:
        btn.click()
    else:
        page.keyboard.press("Enter")

    # Success = redirect to /dashboard.
    log("waiting for dashboard redirect ...")
    try:
        page.wait_for_url("**/dashboard**", timeout=timeout_ms)
        log("reached dashboard")
        return True, ""
    except PwTimeout:
        err = page.evaluate(
            """() => document.body.innerText.slice(0, 800)"""
        ) or ""
        m = re.search(r"(Something went wrong[^\n]{0,120}|"
                      r"already[^.\n]{0,80}|"
                      r"Invalid[^\n]{0,80}|"
                      r"try again[^\n]{0,80})", err)
        detail = m.group(1) if m else "no dashboard redirect"
        return False, detail


def browser_signup(email: str, password: str,
                   headless: bool = True,
                   timeout_ms: int = 120_000,
                   proxy: Optional[str] = None,
                   verbose: bool = True) -> dict:
    """Run a real-browser signup. Returns {'ok', 'email', 'password', 'error'}."""
    def log(msg: str):
        if verbose:
            print(f"    [browser] {msg}", flush=True)

    with sync_playwright() as p:
        log("launching Chromium ...")
        browser, ctx = _launch_browser(p, headless, proxy)
        page = ctx.new_page()
        try:
            log(f"opening {SIGNUP_URL} ...")
            page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=60000)
            ok, detail = _do_signup(page, email, password,
                                    timeout_ms=timeout_ms, verbose=verbose)
            if ok:
                return {"ok": True, "email": email, "password": password}
            # Deep diagnostics: screenshot + page state.
            shot = f"/tmp/signup-fail-{int(time.time())}.png"
            try:
                page.screenshot(path=shot)
                log(f"screenshot saved: {shot}")
            except Exception:
                pass
            ts = page.evaluate(
                """() => {
                    const iframes = document.querySelectorAll(
                        'iframe[src*="turnstile"], iframe[src*="cloudflare"]');
                    const widget = document.querySelector('.cf-turnstile');
                    return {iframes: iframes.length,
                            widget: !!widget,
                            token: !!(document.querySelector(
                                'input[name="cf-turnstile-response"]') || {}).value};
                }"""
            ) or {}
            log(f"after submit: url={page.url} turnstile={ts}")
            log(f"FAIL: {detail}")
            return {"ok": False, "email": email, "password": password,
                    "error": detail, "screenshot": shot,
                    "page_url": page.url, "turnstile_state": ts}
        finally:
            ctx.close()
            browser.close()


def _make_email_client(provider: str = "tempmail"):
    """Create the disposable-email client for the chosen provider.

    tempik   -> TempikClient (user's own Tempik instance)
    tempmail -> TempMailLolClient (tempmail.lol, no setup needed)
    """
    if provider == "tempmail":
        from .tempmail_lol import TempMailLolClient
        return TempMailLolClient()
    from .tempik import TempikClient
    return TempikClient()


def _click_if_visible(page, selector: str, wait_ms: int = 2000) -> bool:
    """Click the first visible element matching selector. Never raises."""
    try:
        loc = page.locator(selector).first
        if loc.is_visible(timeout=5000):
            loc.click()
            page.wait_for_timeout(wait_ms)
            return True
    except Exception:
        pass
    return False


def _dismiss_free_models_dialog(page) -> bool:
    """Click 'Enable free models' on the first-visit dialog, if present."""
    ok = _click_if_visible(page, 'button:has-text("Enable free models")')
    if ok:
        print("    [browser] free-models dialog: enabled", flush=True)
    return ok


def _click_verify_email_button(page) -> bool:
    """Click the dashboard 'Verify email' banner button, if present."""
    ok = _click_if_visible(
        page, 'button:has-text("Verify email"), a:has-text("Verify email")')
    if ok:
        print("    [browser] verify-email button clicked", flush=True)
    return ok


def _extract_verify_link(msg: dict) -> Optional[str]:
    """Pull the TokenHarbor verify link out of a mailbox message dict."""
    parts = []
    for key in ("body", "html", "text"):
        val = msg.get(key, "") or ""
        if isinstance(val, list):
            val = val[0] if val else ""
        if val:
            parts.append(str(val))
    content = " ".join(parts)
    m = re.search(r"https://tokenharbor\.ai/verify-email\?[^\s\"<>]+", content)
    return m.group(0) if m else None


def _inpage_post(page, path: str, payload: dict):
    """POST JSON to the site's own API from inside the page (cookies apply)."""
    return page.evaluate(
        """async ([path, payload]) => {
            const r = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            try { return await r.json(); }
            catch (e) { return {error: 'non-json status ' + r.status}; }
        }""",
        [path, payload],
    )


def auto_farm_one(headless: bool = True,
                  proxy: Optional[str] = None,
                  email_provider: str = "tempmail") -> dict:
    """Full-browser pipeline: disposable email -> browser signup ->
    verify (same session) -> enable free models -> API key (in-page).
    Returns an account dict in the same shape the CLI/monitor expect:
    {'ok', 'email', 'password', 'api_key', 'free_models'} on success,
    {'ok': False, 'stage', 'email', 'password', 'error'} on failure.
    All 'error' values are strings.
    """
    t = _make_email_client(email_provider)
    inbox = t.create_inbox()
    email = inbox["address"] if isinstance(inbox, dict) else inbox
    password = _gen_password()
    print(f"[*] browser signup for {email} ...")
    with sync_playwright() as p:
        print("    [browser] launching Chromium ...", flush=True)
        browser, ctx = _launch_browser(p, headless, proxy)
        page = ctx.new_page()
        try:
            page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=60000)
            ok, detail = _do_signup(page, email, password, verbose=True)
            if not ok:
                return {"ok": False, "stage": "browser_signup", "email": email,
                        "password": password, "error": str(detail)}
            # First dashboard visit may show the free-models dialog.
            _dismiss_free_models_dialog(page)
            # Trigger the verification email (sent on demand).
            print("[*] triggering verification email ...")
            _click_verify_email_button(page)
            print("[*] verifying email ...")
            msg = t.wait_for_message(email, timeout=120)
            link = _extract_verify_link(msg) if msg else None
            if not link:
                return {"ok": False, "stage": "verify_email", "email": email,
                        "password": password,
                        "error": "verification link not found in inbox"}
            page.goto(link, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_url("**/dashboard**", timeout=30000)
            except PwTimeout:
                cur = page.url or ""
                if "success" not in cur.lower():
                    return {"ok": False, "stage": "verify_email", "email": email,
                            "password": password,
                            "error": f"verify link did not reach dashboard (url: {cur.split('?')[0]})"}
            _dismiss_free_models_dialog(page)
            print("[*] enabling free models ...")
            fr = _inpage_post(page, "/api/me/privacy",
                              {"consent_version": 2, "free_models_enabled": True})
            fr_ok = isinstance(fr, dict) and ("error" not in fr)
            print("[*] creating API key ...")
            kr = _inpage_post(page, "/api/keys", {"label": "auto-farm"})
            api_key = None
            if isinstance(kr, dict):
                api_key = kr.get("plaintext") or (kr.get("key") or {}).get("plaintext")
                if not api_key:
                    m = re.search(r"thk_live_[A-Za-z0-9_-]+", json.dumps(kr))
                    if m:
                        api_key = m.group(0)
            if not api_key:
                keys = sorted(kr.keys()) if isinstance(kr, dict) else type(kr).__name__
                err = str(kr.get("error", ""))[:120] if isinstance(kr, dict) else ""
                return {"ok": False, "stage": "api_key", "email": email,
                        "password": password,
                        "error": f"key not in response (keys: {keys} err: {err})"}
            return {"ok": True, "email": email, "password": password,
                    "api_key": api_key, "free_models": fr_ok}
        finally:
            ctx.close()
            browser.close()


def _gen_password(length: int = 16) -> str:
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))
