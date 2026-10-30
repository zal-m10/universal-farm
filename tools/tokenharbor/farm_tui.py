"""Interactive TUI for TokenHarbor + Mistral farming.

Launched via the `farm` command after running install.sh.
Main menu: Farm TokenHarbor | Farm Mistral | Farm Dahl | Farm GonkaRouter | Farm Nscale |
           Delay setting | Setup Proxy
Each farm has its own submenu with Run farm / Results.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table

console = Console()

REPO_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"
PROXY_PATH = REPO_DIR / "tools" / "proxies.txt"
CAPSOLVER_PATH = Path(__file__).resolve().parent / ".capsolver_key"
RESULTS_PATH = REPO_DIR / "account.json"
TUI_STATE = Path.home() / ".farm_tui.json"

MISTRAL_SCRIPT = Path("/root/mistral_farm.py")
MISTRAL_KEYS = Path("/root/mistral_keys.txt")
DAHL_SCRIPT = Path("/root/dahl_farm.py")
DAHL_KEYS = Path("/root/dahl_keys.txt")
GONKA_SCRIPT = Path("/root/gonka_farm_email.py")
GONKA_KEYS = Path("/root/gonka_keys.txt")

def _resolve_script(path: Path, repo_fallback: str) -> Path:
    """Return path if it exists, else repo fallback if that exists."""
    if path.exists():
        return path
    fb = REPO_DIR / repo_fallback
    return fb if fb.exists() else path

DEFAULT_DELAY = 60


def _load_state() -> dict:
    if TUI_STATE.exists():
        try:
            return json.loads(TUI_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"delay": DEFAULT_DELAY,
            "tokenharbor_auto_inject": False,
            "tokenharbor_auto_inject_omniroute": False,
            "mistral_auto_inject": False,
            "mistral_auto_inject_omniroute": False,
            "dahl_auto_inject": False,
            "dahl_auto_inject_omniroute": False,
            "gonka_auto_inject": False,
            "gonka_auto_inject_omniroute": False}


def _save_state(state: dict) -> None:
    TUI_STATE.write_text(json.dumps(state, indent=2))


def _get_tempik_url() -> str | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        import tomllib
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
        url = cfg.get("tempik", {}).get("base_url", "")
        return url or None
    except Exception:
        return None


def _set_tempik_url(url: str) -> None:
    import tomllib
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
    cfg.setdefault("tokenharbor", {})["base_url"] = "https://tokenharbor.ai"
    cfg.setdefault("tokenharbor", {})["turnstile_sitekey"] = "0x4AAAAAADBuC8Knz1EJZx9-"
    cfg.setdefault("tempik", {})["base_url"] = url
    files = cfg.setdefault("files", {})
    files.setdefault("capsolver_key", "tools/tokenharbor/.capsolver_key")
    files.setdefault("proxy_list", "tools/proxies.txt")
    files.setdefault("account_output", "account.json")
    cfg.setdefault("models", {})["free"] = [
        "deepseek-v4-flash:free",
        "mimo-v2.5:free",
        "qwen3.8-27b:free",
    ]
    # Write back as TOML manually (no writer dep).
    lines = []
    for section, vals in cfg.items():
        lines.append(f"[{section}]")
        for k, v in vals.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, list):
                items = ", ".join(f'"{x}"' for x in v)
                lines.append(f"{k} = [{items}]")
            else:
                lines.append(f"{k} = {v}")
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines))


def _get_proxies() -> list:
    """Return all configured proxies (one per line)."""
    if PROXY_PATH.exists():
        lines = PROXY_PATH.read_text().strip().splitlines()
        return [x.strip() for x in lines
                if x.strip() and not x.strip().startswith("#")]
    return []


def _get_proxy() -> str | None:
    proxies = _get_proxies()
    return proxies[0] if proxies else None


def _set_proxies(proxies: list) -> None:
    PROXY_PATH.write_text("\n".join(p.strip() for p in proxies if p.strip()) + "\n")


def _clear_screen():
    console.clear()


def _gradient_text(text: str, stops: list) -> "Text":
    """Apply horizontal gradient across text. stops = [(pos, (r,g,b)), ...]."""
    from rich.text import Text
    out = Text()
    chars = list(text)
    n = len(chars)
    for i, ch in enumerate(chars):
        t = i / max(n - 1, 1)
        # Find surrounding stops.
        for s in range(len(stops) - 1):
            p0, c0 = stops[s]
            p1, c1 = stops[s + 1]
            if p0 <= t <= p1:
                f = (t - p0) / max(p1 - p0, 1e-9)
                r = int(c0[0] + (c1[0] - c0[0]) * f)
                g = int(c0[1] + (c1[1] - c0[1]) * f)
                b = int(c0[2] + (c1[2] - c0[2]) * f)
                break
        else:
            r, g, b = stops[-1][1]
        if ch == " ":
            out.append(ch)
        else:
            out.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return out


FARM_ART = [
    "███████╗ █████╗ ██████╗ ███╗   ███╗",
    "██╔════╝██╔══██╗██╔══██╗████╗ ████║",
    "█████╗  ███████║██████╔╝██╔████╔██║",
    "██╔══╝  ██╔══██║██╔══██╗██║╚██╔╝██║",
    "██║     ██║  ██║██║  ██║██║ ╚═╝ ██║",
    "╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝",
]
# Orange -> pink -> purple (like the KEDAI VPN photo).
FARM_GRADIENT = [
    (0.0, (255, 165, 0)),    # orange
    (0.5, (255, 20, 147)),    # pink
    (1.0, (148, 0, 211)),     # purple
]
FARM_INDENT = " " * 21


def _farm_header():
    for line in FARM_ART:
        console.print(Text(FARM_INDENT) + _gradient_text(line, FARM_GRADIENT))
    console.print(_gradient_text(" " * 22 + "Universal Farm — Interactive TUI",
                                 [(0.0, (255, 20, 147)), (1.0, (148, 0, 211))]))


TUI_BANNER = r"""
[bold cyan]
                     ███████╗ █████╗ ██████╗ ███╗   ███╗
                     ██╔════╝██╔══██╗██╔══██╗████╗ ████║
                     █████╗  ███████║██████╔╝██╔████╔██║
                     ██╔══╝  ██╔══██║██╔══██╗██║╚██╔╝██║
                     ██║     ██║  ██║██║  ██║██║ ╚═╝ ██║
                     ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
[/bold cyan]
[bold bright_cyan]                    TokenHarbor Farm — Interactive TUI[/bold bright_cyan]
"""


HARBOR_BANNER = r"""
[bold cyan]
               ██╗  ██╗ █████╗ ██████╗ ██████╗  ██████╗ ██████╗
               ██║  ██║██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔══██╗
               ███████║███████║██████╔╝██████╔╝██║   ██║██████╔╝
               ██╔══██║██╔══██║██╔══██╗██╔══██╗██║   ██║██╔══██╗
               ██║  ██║██║  ██║██║  ██║██████╔╝╚██████╔╝██║  ██║
               ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝
[/bold cyan]
[bold bright_cyan]                 TokenHarbor Auto CLI — HTTP Mode • Chromium[/bold bright_cyan]
[dim italic]                              FORKED FROM MASANTOID[/dim italic]
"""


def _header():
    _farm_header()


MISTRAL_BANNER = r"""
[bold magenta]
               ███╗   ███╗██╗███████╗████████╗██████╗  █████╗ ██╗
               ████╗ ████║██║██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██║
               ██╔████╔██║██║███████╗   ██║   ██████╔╝███████║██║
               ██║╚██╔╝██║██║╚════██║   ██║   ██╔══██╗██╔══██║██║
               ██║ ╚═╝ ██║██║███████║   ██║   ██║  ██║██║  ██║███████╗
               ╚═╝     ╚═╝╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝
[/bold magenta]
[bold bright_magenta]              Mistral Farm Auto CLI — HTTP Mode • No Browser[/bold bright_magenta]
"""


def _mistral_header():
    console.print(MISTRAL_BANNER)


DAHL_BANNER = r"""
[bold green]
                         ██████╗  █████╗ ██╗  ██╗██╗
                         ██╔══██╗██╔══██╗██║  ██║██║
                         ██║  ██║███████║███████║██║
                         ██║  ██║██╔══██║██╔══██║██║
                         ██████╔╝██║  ██║██║  ██║███████╗
                         ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝
[/bold green]
[bold bright_green]                   Dahl Farm Auto CLI — HTTP Mode • No Browser[/bold bright_green]
"""


def _dahl_header():
    console.print(DAHL_BANNER)


GONKA_BANNER = r"""
[bold white]
 ██████╗  ██████╗ ███╗   ██╗██╗  ██╗ █████╗
██╔════╝ ██╔═══██╗████╗  ██║██║ ██╔╝██╔══██╗
██║  ███╗██║   ██║██╔██╗ ██║█████╔╝ ███████║
██║   ██║██║   ██║██║╚██╗██║██╔═██╗ ██╔══██║
╚██████╔╝╚██████╔╝██║ ╚████║██║  ██╗██║  ██║
 ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝
[/bold white]
[bold white]GonkaRouter Farm Auto CLI — Email + OTP Mode[/bold white]
"""


def _gonka_header():
    console.print(GONKA_BANNER, justify="center")

NSCALE_BANNER = r"""
[bold cyan]
 ███╗   ██╗███████╗ ██████╗ █████╗ ██╗     ███████╗
 ████╗  ██║██╔════╝██╔════╝██╔══██╗██║     ██╔════╝
 ██╔██╗ ██║███████╗██║     ███████║██║     █████╗  
 ██║╚██╗██║╚════██║██║     ██╔══██║██║     ██╔══╝  
 ██║ ╚████║███████║╚██████╗██║  ██║███████╗███████╗
 ╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝
[/bold cyan]
[bold bright_cyan]Nscale Farm — Real Chrome • Headed[/bold bright_cyan]
"""


def _nscale_header():
    console.print(NSCALE_BANNER, justify="center")



def _harbor_header():
    console.print(HARBOR_BANNER)


def _status_line(state: dict, proxies: list, tempik, capsolver) -> None:
    def dot(ok: bool) -> str:
        return "[bright_green]●[/bright_green]" if ok else "[bright_red]●[/bright_red]"
    proxy_txt = f"{len(proxies)} proxies" if proxies else "no proxy"
    email_provider = state.get("tokenharbor_email_provider", "tempmail")
    capsolver_on = state.get("capsolver_enabled", bool(capsolver)) and bool(capsolver)
    console.print(
        f"{dot(bool(proxies))} [white]{proxy_txt}[/white]   "
        f"{dot(True)} [white]email:{email_provider}[/white]   "
        f"{dot(capsolver_on)} [white]capsolver[/white]   "
        f"[dim]│[/dim]   [dim]delay[/dim] [cyan]{state['delay']}s[/cyan]",
        justify="center",
    )


def _get_capsolver() -> str | None:
    if CAPSOLVER_PATH.exists():
        k = CAPSOLVER_PATH.read_text().strip()
        return k or None
    return None


def _set_capsolver(key: str) -> None:
    CAPSOLVER_PATH.write_text(key.strip() + "\n")
    os.chmod(CAPSOLVER_PATH, 0o600)


def menu_setup_capsolver():
    _clear_screen(); _header()
    state = _load_state()
    enabled = state.get("capsolver_enabled", bool(_get_capsolver()))
    current = _get_capsolver()
    masked = (current[:8] + "..." if current else "-")
    status = "[green]ON[/green]" if enabled else "[dim]OFF[/dim]"
    console.print(f"\nCapsolver: {status}")
    console.print(f"Current key: [cyan]{masked}[/cyan]\n")
    console.print("[1] Toggle ON/OFF")
    console.print("[2] Set API key")
    console.print("[3] Clear key")
    console.print("[0] Back\n")
    choice = Prompt.ask("Select", choices=["0", "1", "2", "3"],
                        default="1", show_choices=False)
    if choice == "1":
        if not enabled and _get_capsolver() is None:
            console.print("[yellow]Capsolver key belum ada \u2014 pilih [2] Set API key dulu.[/yellow]")
        else:
            state["capsolver_enabled"] = not enabled
            _save_state(state)
            console.print(f"[green]Capsolver {'disabled' if enabled else 'enabled'}.[/green]")
    elif choice == "2":
        val = Prompt.ask("Enter Capsolver API key (empty to cancel)", password=True)
        if val.strip():
            _set_capsolver(val)
            state["capsolver_enabled"] = True
            _save_state(state)
            console.print("[green]Capsolver key saved and enabled.[/green]")
    elif choice == "3":
        if CAPSOLVER_PATH.exists():
            CAPSOLVER_PATH.unlink()
        state["capsolver_enabled"] = False
        _save_state(state)
        console.print("[yellow]Capsolver key cleared and disabled.[/yellow]")
    else:
        return
    Prompt.ask("\nPress Enter to continue", default="")


def menu_setup_proxy():
    while True:
        _clear_screen(); _header()
        proxies = _get_proxies()
        console.print(f"\n[bold]Proxy management[/bold] — [cyan]{len(proxies)}[/cyan] configured\n")
        console.print("\\[1] Add proxy (bulk paste)")
        console.print("\\[2] Select to delete (multi-select)")
        console.print("[3] Delete all proxies")
        console.print("[0] Back\n")
        choice = Prompt.ask("Select", choices=["0", "1", "2", "3"],
                            default="1", show_choices=False)
        if choice == "1":
            _proxy_add_bulk()
        elif choice == "2":
            _proxy_select_delete()
        elif choice == "3":
            _proxy_delete_all()
        else:
            return


def _proxy_add_bulk():
    _clear_screen(); _header()
    console.print("\n[dim]Format per line: user:pass@host:port[/dim]")
    console.print("[dim]Paste proxies (one per line). Type DONE on its own line when finished.[/dim]\n")
    lines = []
    while True:
        try:
            line = input("proxy> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Cancelled.[/yellow]")
            Prompt.ask("\nPress Enter to continue", default="")
            return
        if line.lower() == "q" and not lines:
            return
        if line.upper() == "DONE":
            break
        if line:
            for part in line.split(","):
                part = part.strip()
                if part and part.upper() != "DONE":
                    lines.append(part)
    if not lines:
        console.print("[dim]No proxies added.[/dim]")
    else:
        existing = _get_proxies()
        _set_proxies(existing + lines)
        console.print(f"[green]{len(lines)} proxy/proxies added ({len(existing) + len(lines)} total).[/green]")
    Prompt.ask("\nPress Enter to continue", default="")


def _proxy_delete_all():
    _clear_screen(); _header()
    proxies = _get_proxies()
    if not proxies:
        console.print("\n[dim]No proxies to delete.[/dim]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    if Confirm.ask(f"\n[red]Delete all {len(proxies)} proxies?[/red]", default=False):
        PROXY_PATH.unlink()
        console.print("[green]✓ All proxies deleted.[/green]")
    else:
        console.print("Cancelled.")
    Prompt.ask("\nPress Enter to continue", default="")


def _proxy_select_delete():
    proxies = _get_proxies()
    if not proxies:
        _clear_screen(); _header()
        console.print("\n[dim]No proxies to delete.[/dim]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    selected = _curses_multiselect(
        "Select proxies to delete (↑↓ navigate, SPACE toggle, ENTER delete, q cancel)",
        proxies,
    )
    if selected is None:
        return  # cancelled
    if not selected:
        _clear_screen(); _header()
        console.print("\n[dim]Nothing selected.[/dim]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    _clear_screen(); _header()
    console.print(f"\n[red]Delete {len(selected)} selected proxy/proxies?[/red]")
    for p in selected:
        masked = p.split("@")[-1] if "@" in p else p
        console.print(f"  • {masked}")
    if Confirm.ask("", default=False):
        remaining = [p for p in proxies if p not in selected]
        if remaining:
            _set_proxies(remaining)
        elif PROXY_PATH.exists():
            PROXY_PATH.unlink()
        console.print(f"[green]✓ {len(selected)} deleted ({len(remaining)} remaining).[/green]")
    else:
        console.print("Cancelled.")
    Prompt.ask("\nPress Enter to continue", default="")


def _curses_multiselect(title: str, items: list) -> list | None:
    """Interactive multi-select. Returns selected items, [] if none, None if cancelled."""
    import curses

    selected_idx = set()
    cursor = 0
    result = {"cancelled": False}

    def draw(stdscr):
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        stdscr.addstr(0, 0, title[:w - 1], curses.A_BOLD)
        stdscr.addstr(1, 0, f"{len(selected_idx)} selected", curses.A_DIM)
        for i, item in enumerate(items):
            y = i + 3
            if y >= h - 1:
                break
            masked = item.split("@")[-1] if "@" in item else item
            mark = "[x]" if i in selected_idx else "[ ]"
            line = f"{mark} {masked}"
            attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
            try:
                stdscr.addstr(y, 2, line[:w - 4], attr)
            except curses.error:
                pass
        stdscr.refresh()

    def loop(stdscr):
        nonlocal cursor
        curses.curs_set(0)
        stdscr.keypad(True)
        while True:
            draw(stdscr)
            key = stdscr.getch()
            if key == curses.KEY_UP:
                cursor = (cursor - 1) % len(items)
            elif key == curses.KEY_DOWN:
                cursor = (cursor + 1) % len(items)
            elif key == ord(" "):
                if cursor in selected_idx:
                    selected_idx.discard(cursor)
                else:
                    selected_idx.add(cursor)
            elif key in (curses.KEY_ENTER, 10, 13):
                break
            elif key in (ord("q"), ord("Q"), 27):  # q / Esc
                result["cancelled"] = True
                break

    try:
        curses.wrapper(loop)
    except Exception:
        return None
    if result["cancelled"]:
        return None
    return [items[i] for i in sorted(selected_idx)]


def menu_setup_tempik():
    _clear_screen(); _harbor_header()
    state = _load_state()
    provider = state.get("tokenharbor_email_provider", "tempmail")
    current = _get_tempik_url()
    console.print(f"\nEmail provider: [cyan]{provider}[/cyan]")
    console.print(f"Tempik URL: [cyan]{current or '-'}[/cyan]\n")
    console.print("[1] Use Tempik (your own domain)")
    console.print("[2] Use Temp Mail (tempmail.lol, no setup needed)")
    console.print("[3] Set Tempik URL")
    console.print("[0] Back\n")
    choice = Prompt.ask("Select", choices=["0", "1", "2", "3"],
                        default="1", show_choices=False)
    if choice == "1":
        state["tokenharbor_email_provider"] = "tempik"
        _save_state(state)
        console.print("[green]Email provider set to Tempik.[/green]")
    elif choice == "2":
        state["tokenharbor_email_provider"] = "tempmail"
        _save_state(state)
        console.print("[green]Email provider set to Temp Mail.[/green]")
    elif choice == "3":
        val = Prompt.ask("Enter Tempik base URL ('q' to cancel)")
        if val.lower() == "q":
            return
        if val.strip():
            _set_tempik_url(val.strip().rstrip("/"))
            console.print("[green]Tempik URL saved.[/green]")
    else:
        return
    Prompt.ask("\nPress Enter to continue", default="")


def menu_delay_setting():
    _clear_screen(); _header()
    state = _load_state()
    console.print(f"\nCurrent delay: [cyan]{state['delay']}s[/cyan]")
    console.print("[dim]Seconds to wait between accounts (rate-limit safety).[/dim]\n")
    val = IntPrompt.ask("Enter delay in seconds", default=state["delay"])
    state["delay"] = max(0, val)
    _save_state(state)
    console.print(f"[green]Delay set to {state['delay']}s.[/green]")
    Prompt.ask("\nPress Enter to continue", default="")


def menu_run_farm():
    _clear_screen(); _harbor_header()
    # Tempik and Capsolver are both optional: the farm also runs with
    # Temp Mail (tempmail.lol) and without any captcha solver.
    state = _load_state()
    email_provider = state.get("tokenharbor_email_provider", "tempmail")
    capsolver_enabled = state.get("capsolver_enabled", bool(_get_capsolver()))

    proxies = _get_proxies()
    if not proxies:
        console.print("\n[yellow]⚠ No proxy configured.[/yellow]")
        if not Confirm.ask("Run without proxy?", default=False):
            console.print("Cancelled. Set proxies via [cyan]Setup proxy[/cyan].")
            Prompt.ask("\nPress Enter to continue", default="")
            return
        proxy_info = "no"
    else:
        proxy_info = f"{len(proxies)} (rotating)"

    count = IntPrompt.ask("\nHow many accounts to farm?", default=1)
    delay = state.get("delay", DEFAULT_DELAY)
    email_label = ("Temp Mail (tempmail.lol)" if email_provider == "tempmail"
                   else f"Tempik ({_get_tempik_url() or 'URL not set'})")
    console.print(f"\n[dim]Email: {email_label}[/dim]")
    console.print(f"[dim]Capsolver: {'ON' if capsolver_enabled else 'OFF'}[/dim]")
    console.print(f"[dim]Proxy: {proxy_info}[/dim]")
    console.print(f"[dim]Delay: {delay}s[/dim]\n")

    if not Confirm.ask(f"Start farming {count} account(s)?", default=True):
        return

    # Snapshot existing keys BEFORE the run (for per-run notification).
    _before_keys_th = set(
        a.get("api_key") for a in _get_accounts() if a.get("api_key")
    )

    # Foreground or background?
    console.print()
    console.print("\\[1] Run in foreground (watch live)")
    console.print("\\[2] Run in background (survives disconnect)")
    bg_choice = Prompt.ask("Mode", choices=["1", "2"], default="1",
                           show_choices=False)

    console.print()
    venv_python = REPO_DIR / ".venv" / "bin" / "python"
    py = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [py, "-m", "tools.tokenharbor.cli", "browser-farm",
           "--count", str(count), "--delay", str(delay),
           "--email-provider", email_provider]

    if bg_choice == "2":
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = f"/tmp/farm-{ts}.log"
        pidfile = Path("/tmp/farm.pid")
        # nohup + detach so it survives SSH disconnect.
        farm_pid = _spawn_detached(cmd, logfile, cwd=str(REPO_DIR))
        pidfile.write_text(str(farm_pid))
        console.print(f"[green]✓ Farm started in background (PID {farm_pid}).[/green]")
        console.print(f"[dim]Log: {logfile}[/dim]")
        console.print("[dim]You can disconnect — it keeps running.[/dim]")
        console.print("[dim]Check progress via menu [2] Results → [b] Background log.[/dim]")
        # Arm monitor if auto-inject ON or Telegram configured.
        state = _load_state()
        if _should_arm_monitor(state, "tokenharbor_auto_inject") or state.get("tokenharbor_auto_inject_omniroute", False):
            _arm_inject_monitor(str(_monitor_path("tokenharbor")), farm_pid, ts, "tokenharbor",
                                count, sorted(_before_keys_th))
    else:
        try:
            subprocess.run(cmd, cwd=str(REPO_DIR))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        # Auto-inject to 9Router if enabled.
        state = _load_state()
        if state.get("tokenharbor_auto_inject", False):
            console.print("\n[dim]Auto-injecting to 9Router...[/dim]")
            added, skipped, err = _inject_tokenharbor_to_9router()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected: {added} new, {skipped} already there.[/green]")
        if state.get("tokenharbor_auto_inject_omniroute", False):
            console.print("\n[dim]Auto-injecting to OmniRoute...[/dim]")
            added, skipped, err = _inject_tokenharbor_to_omniroute()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected to OmniRoute: {added} new, {skipped} already there.[/green]")
        # Telegram notification — only keys from THIS run.
        try:
            accounts = _get_accounts()
            new = [
                a for a in accounts
                if a.get("ok") and a.get("api_key")
                and a["api_key"] not in _before_keys_th
            ]
            new_keys = [a["api_key"] for a in new]
            success = min(len(new_keys), count)
            _notify_farm_done("TokenHarbor", count, success, count - success,
                              new_keys[:count],
                              emails=[a.get("email", "") for a in new[:count]])
        except Exception:
            pass
    Prompt.ask("\nPress Enter to continue", default="")


def _count_running_farms() -> int:
    """Count background farm processes currently alive."""
    count = 0
    # Check PID file.
    pidfile = Path("/tmp/farm.pid")
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            count += 1
        except (ValueError, OSError):
            pass
    # Also scan for browser-farm processes not in pidfile.
    try:
        out = subprocess.run(["pgrep", "-f", "browser-farm"],
                             capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.strip().split("\n") if p.strip()]
        # Subtract the one we already counted via pidfile.
        if pidfile.exists():
            try:
                known = pidfile.read_text().strip()
                pids = [p for p in pids if p != known]
            except OSError:
                pass
        count += len(pids)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return count


def _count_failed_from_logs() -> int:
    """Count 'Failed at' occurrences across farm log files."""
    total = 0
    for log in Path("/tmp").glob("farm-*.log"):
        try:
            text = log.read_text()
            total += text.count("✗ Failed at")
        except OSError:
            pass
    return total


def _get_accounts() -> list:
    """Read all TokenHarbor farm accounts from account.json."""
    if not RESULTS_PATH.exists():
        return []
    try:
        data = json.loads(RESULTS_PATH.read_text())
        accounts = data if isinstance(data, list) else [data]
        return accounts if isinstance(accounts, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def menu_results():
    _clear_screen(); _harbor_header()
    # Gather stats even if account.json doesn't exist yet.
    accounts = []
    if RESULTS_PATH.exists():
        try:
            data = json.loads(RESULTS_PATH.read_text())
            accounts = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            console.print("\n[red]Results file is corrupted.[/red]")
    ok = [a for a in accounts if a.get("ok")]
    fail_file = [a for a in accounts if not a.get("ok")]

    running = _count_running_farms()
    failed_logs = _count_failed_from_logs()
    failed_total = len(fail_file) + failed_logs

    console.print(f"\n[bold]Running: [cyan]{running}[/cyan] | "
                  f"[green]Success: {len(ok)}[/green] | "
                  f"[red]Failed: {failed_total}[/red][/bold]\n")
    if not accounts and not failed_logs and running == 0:
        console.print("[dim]No results yet. Run farm first.[/dim]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    if ok:
        t = Table(title="Farmed accounts", show_lines=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Email", style="magenta")
        t.add_column("API key", style="green")
        t.add_column("Free models", width=11)
        for i, a in enumerate(ok, 1):
            t.add_row(str(i), a.get("email", "-"),
                      a.get("api_key", "-"),
                      "yes" if a.get("free_models") else "no")
        console.print(t)
    if fail_file:
        console.print("\n[red]Failed:[/red]")
        for a in fail_file:
            console.print(f"  • {a.get('email', '?')}: "
                          f"{a.get('stage', '?')} — {a.get('error', '?')}")

    # Sub-menu: use Text to avoid Rich parsing [c]/[d]/[b] as color tags.
    from rich.text import Text as _Text
    console.print()
    bar = _Text()
    if ok:
        bar.append("[c] ", style="bold cyan")
        bar.append("Copy all API  ")
        bar.append("[d] ", style="bold cyan")
        bar.append("Delete all results  ")
    pidfile = Path("/tmp/farm.pid")
    bg_running = False
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            bg_running = True
        except (ValueError, OSError):
            pass
    has_logs = bool(list(Path("/tmp").glob("farm-*.log")))
    if bg_running or has_logs:
        bar.append("[b] ", style="bold cyan")
        bar.append("Background log  ")
    bar.append("[Enter] ", style="bold cyan")
    bar.append("Back to menu")
    console.print(bar)
    choices = ["c", "d", "b", ""] if ok else (["b", ""] if (bg_running or has_logs) else [""])
    action = Prompt.ask("Action", choices=choices,
                        default="", show_choices=False)
    if action == "c" and ok:
        _copy_keys(ok)
    elif action == "d" and ok:
        _delete_results()
    elif action == "b":
        _show_bg_log()
    else:
        Prompt.ask("\nPress Enter to continue", default="")


def _copy_keys(accounts: list) -> None:
    keys = [a.get("api_key", "") for a in accounts if a.get("api_key")]
    text = "\n".join(keys)
    copied = False
    # Try system clipboard.
    for cmd in (["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"]):
        try:
            subprocess.run(cmd, input=text.encode(), timeout=5,
                           capture_output=True)
            copied = True
            break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    # Always also save to a file for easy retrieval over SSH.
    keys_file = REPO_DIR / "keys.txt"
    keys_file.write_text(text + "\n")
    console.print(f"\n[green]✓ {len(keys)} keys ready.[/green]")
    if copied:
        console.print("[dim]Copied to clipboard.[/dim]")
    console.print(f"[dim]Also saved to: {keys_file}[/dim]")
    console.print("\n[bold]Keys:[/bold]")
    for k in keys:
        console.print(f"  {k}")
    Prompt.ask("\nPress Enter to continue", default="")


def _show_bg_log() -> None:
    logs = sorted(Path("/tmp").glob("farm-*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        console.print("\n[dim]No background farm logs found.[/dim]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    latest = logs[-1]
    # Check if still running.
    pidfile = Path("/tmp/farm.pid")
    running = False
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text().strip()), 0)
            running = True
        except (ValueError, OSError):
            pass
    status = "[green]RUNNING[/green]" if running else "[dim]finished[/dim]"
    console.print(f"\n[bold]Background farm:[/bold] {status}")
    console.print(f"[dim]Log: {latest}[/dim]\n")
    try:
        lines = latest.read_text().splitlines()
    except OSError:
        lines = []
    # Show last 30 lines.
    for line in lines[-30:]:
        console.print(f"  {line}")
    if running:
        console.print("\n[dim]Still running — check again later for updates.[/dim]")
    Prompt.ask("\nPress Enter to continue", default="")


def _delete_results() -> None:
    if not Confirm.ask("\n[red]Delete ALL farm results (emails + keys + logs)?[/red]",
                       default=False):
        console.print("Cancelled.")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    if RESULTS_PATH.exists():
        RESULTS_PATH.unlink()
    keys_file = REPO_DIR / "keys.txt"
    if keys_file.exists():
        keys_file.unlink()
    # Clear farm logs so the Failed counter resets too.
    for log in Path("/tmp").glob("farm-*.log"):
        try:
            log.unlink()
        except OSError:
            pass
    # Clear stale PID file.
    pidfile = Path("/tmp/farm.pid")
    if pidfile.exists():
        try:
            pidfile.unlink()
        except OSError:
            pass
    console.print("[green]✓ All results deleted (counter reset).[/green]")
    Prompt.ask("\nPress Enter to continue", default="")


def menu_tokenharbor():
    """TokenHarbor submenu (was the old main menu)."""
    while True:
        _clear_screen()
        _harbor_header()
        console.print()
        state = _load_state()
        proxies = _get_proxies()
        tempik = _get_tempik_url()
        capsolver = _get_capsolver()

        _status_line(state, proxies, tempik, capsolver)
        th_inject_on = state.get("tokenharbor_auto_inject", False)
        th_inject_om = state.get("tokenharbor_auto_inject_omniroute", False)
        console.print(f"  [dim]auto-inject:[/dim] 9Router {'[green]ON[/green]' if th_inject_on else '[dim]OFF[/dim]'}"
                      f" · OmniRoute {'[green]ON[/green]' if th_inject_om else '[dim]OFF[/dim]'}",
                      justify="center")
        console.print()

        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", style="bold bright_cyan", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Run farm", "start farming accounts")
        menu.add_row("[2]", "Results", "view farmed accounts")
        _email_provider = state.get("tokenharbor_email_provider", "tempmail")
        menu.add_row("[3]", "Setup email", f"currently: {_email_provider}")
        menu.add_row("[4]", "Auto inject", f"9Router {('ON' if th_inject_on else 'OFF')} · OmniRoute {('ON' if th_inject_om else 'OFF')}")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3", "4"],
                            default="1", show_choices=False, show_default=False)
        if choice == "1":
            menu_run_farm()
        elif choice == "2":
            menu_results()
        elif choice == "3":
            menu_setup_tempik()
        elif choice == "4":
            menu_tokenharbor_inject_toggle()
        else:
            return


# ═══════════════════════════════════════════════════════════════════════════════

# --- GSuite accounts for Nscale farm (bulk / single entry) ---
# Stored in the same accounts.txt the Nscale farm script reads:
# one email:password per line, file mode 600. Passwords are never
# printed or logged; only email counts and names are shown.
def _nscale_accounts_path() -> Path:
    base = Path(os.environ.get("NSCALE_DIR", str(Path.home() / "nscale-farm")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "accounts.txt"


def _load_nscale_accounts() -> list[tuple[str, str]]:
    path = _nscale_accounts_path()
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


def _add_nscale_accounts(new: list[tuple[str, str]]) -> tuple[int, int]:
    """Append new accounts, skipping emails already stored. Returns (added, skipped)."""
    existing = _load_nscale_accounts()
    seen = {e for e, _ in existing}
    added = 0
    for email, password in new:
        if email in seen:
            continue
        existing.append((email, password))
        seen.add(email)
        added += 1
    path = _nscale_accounts_path()
    path.write_text("".join(f"{e}:{pw}" + chr(10) for e, pw in existing), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return added, len(new) - added


def menu_setup_gsuite():
    """Submenu: enter GSuite accounts for Nscale farming, bulk or single."""
    while True:
        _clear_screen()
        accounts = _load_nscale_accounts()
        _header()
        console.print(f"[dim]{len(accounts)} akun tersimpan[/dim]")
        console.print()
        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Bulk", "banyak email, satu password untuk semua")
        menu.add_row("[2]", "Single", "satu email, satu password")
        menu.add_row("[3]", "Lihat akun", "daftar email tersimpan (tanpa password)")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3"],
                            default="0", show_choices=False, show_default=False)
        if choice == "0":
            return
        if choice == "3":
            console.print(f"[dim]File: {_nscale_accounts_path()}[/dim]")
            if not accounts:
                console.print("[yellow]Belum ada akun tersimpan.[/yellow]")
            for i, (email, _pw) in enumerate(accounts, 1):
                console.print(f"  {i}. {email}")
            Prompt.ask("Press Enter to continue", default="")
            continue
        if choice == "1":
            console.print("[dim]Masukkan email satu per satu, kosongkan untuk selesai.[/dim]")
            emails: list[str] = []
            while True:
                email = Prompt.ask("Email", default="").strip().lower()
                if not email:
                    break
                if "@" not in email:
                    console.print("[red]Email tidak valid, dilewati.[/red]")
                    continue
                if email not in emails:
                    emails.append(email)
            if not emails:
                console.print("[yellow]Tidak ada email dimasukkan.[/yellow]")
                Prompt.ask("Press Enter to continue", default="")
                continue
            password = Prompt.ask("Password untuk semua akun di atas", password=True)
            if not password:
                console.print("[yellow]Password kosong, dibatalkan.[/yellow]")
                Prompt.ask("Press Enter to continue", default="")
                continue
            if not Confirm.ask(f"Simpan {len(emails)} akun dengan password yang sama?", default=True):
                continue
            added, skipped = _add_nscale_accounts([(e, password) for e in emails])
            console.print(f"[green]Tersimpan: {added} baru, {skipped} sudah ada.[/green]")
            Prompt.ask("Press Enter to continue", default="")
        else:
            email = Prompt.ask("Email").strip().lower()
            if "@" not in email:
                console.print("[red]Email tidak valid.[/red]")
                Prompt.ask("Press Enter to continue", default="")
                continue
            password = Prompt.ask("Password", password=True)
            if not password:
                console.print("[yellow]Password kosong, dibatalkan.[/yellow]")
                Prompt.ask("Press Enter to continue", default="")
                continue
            added, skipped = _add_nscale_accounts([(email, password)])
            if added:
                console.print(f"[green]Akun {email} tersimpan.[/green]")
            else:
                console.print(f"[yellow]Akun {email} sudah ada, dilewati.[/yellow]")
            Prompt.ask("Press Enter to continue", default="")

# --- Nscale farm (Google SSO, real Chrome only) ---
# The farm script lives in tools/nscale/nscale_farm.py and is run
# through tools/nscale/batch_farm.py, which forces the proven setup:
# real Google Chrome, headed under xvfb, fresh visitorId per account,
# no stealth script. Playwright Chromium is rejected by Nscale
# onboarding with 403 Access denied, so Chrome is mandatory.
NSCALE_SCRIPT_DIR = REPO_DIR / "tools" / "nscale"
NSCALE_BASE_URL = "https://inference.api.nscale.com/v1"
NSCALE_DEFAULT_MODEL = "Qwen/Qwen3-4B-Thinking-2507"


def _nscale_results_path() -> Path:
    return Path(os.environ.get("NSCALE_DIR", str(Path.home() / "nscale-farm"))) / "nscale_accounts.json"


def _get_nscale_results() -> list[dict]:
    path = _nscale_results_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _nscale_done_emails() -> set[str]:
    """Emails already farmed: results file plus 9Router Nscale connections."""
    done = {str(d.get("email", "")).strip().lower() for d in _get_nscale_results() if d.get("email")}
    try:
        import sqlite3
        db = _9r_db_path()
        if db is not None:
            conn = sqlite3.connect(str(db))
            row = conn.execute("SELECT id FROM providerNodes WHERE json_extract(data, '$.baseUrl') = ?", (NSCALE_BASE_URL,)).fetchone()
            if row:
                for (name,) in conn.execute("SELECT name FROM providerConnections WHERE provider = ?", (row[0],)):
                    if name:
                        done.add(str(name).strip().lower())
            conn.close()
    except Exception:
        pass
    return done


def _inject_nscale_to_9router() -> tuple:
    """Inject Nscale service tokens into 9Router SQLite. Returns (added, skipped, error)."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    db = _9r_db_path()
    if db is None:
        return 0, 0, "9Router is not installed on this server."
    def now():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    try:
        conn = sqlite3.connect(str(db))
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"
    try:
        row = None
        try:
            row = conn.execute("SELECT id, data FROM providerNodes WHERE json_extract(data, '$.baseUrl') = ?", (NSCALE_BASE_URL,)).fetchone()
        except Exception:
            row = None
        if row:
            node_id = row[0]
            try:
                prefix = (json.loads(row[1]) or {}).get('prefix') or 'nsc'
            except Exception:
                prefix = 'nsc'
        else:
            node_id = f'openai-compatible-chat-{uuid.uuid4()}'
            prefix = 'nsc'
            data = json.dumps({'prefix': prefix, 'apiType': 'chat', 'baseUrl': NSCALE_BASE_URL, 'nodeName': 'Nscale'})
            conn.execute('INSERT INTO providerNodes (id,type,name,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?)', (node_id, 'openai-compatible', 'Nscale', data, now(), now()))
            conn.commit()
        have = set()
        for (raw,) in conn.execute('SELECT data FROM providerConnections WHERE provider=?', (node_id,)):
            try:
                k = (json.loads(raw) or {}).get('apiKey')
                if k:
                    have.add(k)
            except Exception:
                pass
        added = skipped = 0
        for a in _get_nscale_results():
            key = a.get("service_token")
            email = str(a.get("email", ""))
            if not key:
                continue
            if key in have:
                skipped += 1
                continue
            name = email.split("@")[0] if "@" in email else email
            data = json.dumps({'defaultModel': NSCALE_DEFAULT_MODEL, 'apiKey': key, 'testStatus': 'active', 'providerSpecificData': {'prefix': prefix, 'apiType': 'chat', 'baseUrl': NSCALE_BASE_URL, 'nodeName': 'Nscale', 'connectionProxyEnabled': False, 'connectionProxyUrl': '', 'connectionNoProxy': ''}})
            conn.execute('INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)', (str(uuid.uuid4()), node_id, 'apikey', name, None, 1, 1, data, now(), now()))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def _inject_nscale_to_omniroute() -> tuple:
    """Inject Nscale service tokens into OmniRoute custom node. Returns (added, skipped, error)."""
    entries = [{'api_key': a["service_token"], 'label': a.get("email", "")}
               for a in _get_nscale_results() if a.get("service_token")]
    return _inject_entries_to_omniroute(
        entries, node={'base_url': NSCALE_BASE_URL,
                        'prefix': 'nsc', 'name': 'Nscale'})

def menu_nscale_run_farm():
    _clear_screen()
    _nscale_header()
    console.print()
    import shutil as _shutil
    if not _shutil.which("google-chrome"):
        console.print("[red]Google Chrome tidak ditemukan. Jalankan install.sh lagi (langkah 4b menginstall Chrome).[/red]")
        Prompt.ask("Press Enter to continue", default="")
        return
    accounts = _load_nscale_accounts()
    if not accounts:
        console.print("[yellow]Belum ada akun. Isi dulu lewat menu utama [12] Setup GSuite accounts.[/yellow]")
        Prompt.ask("Press Enter to continue", default="")
        return
    done = _nscale_done_emails()
    pending = [(i, e) for i, (e, _pw) in enumerate(accounts, 1) if e not in done and e.split("@")[0] not in done]
    _proxies = _get_proxies()
    console.print(f"[dim]Proxy: {len(_proxies)} (rotating)[/dim]" if _proxies else "[dim]Proxy: none (direct)[/dim]")
    if not _proxies:
        console.print("[yellow]No proxy configured.[/yellow]")
        if not Confirm.ask("Run without proxy?", default=True):
            console.print("Cancelled. Set proxies via main menu [magenta]Setup Proxy[/magenta].")
            Prompt.ask("Press Enter to continue", default="")
            return
    console.print(f"[dim]Total akun: {len(accounts)} | sudah selesai: {len(accounts) - len(pending)} | pending: {len(pending)}[/dim]")
    if not pending:
        console.print("[green]Semua akun sudah selesai.[/green]")
        Prompt.ask("Press Enter to continue", default="")
        return
    count = IntPrompt.ask("How many accounts to farm?", default=len(pending))
    count = max(1, min(int(count), len(pending)))
    chosen = pending[:count]
    before_tokens = [a.get("service_token", "") for a in _get_nscale_results() if a.get("service_token")]
    console.print(f"[dim]Akan difarm: {', '.join(e for _i, e in chosen)}[/dim]")
    console.print("[1] Run in foreground (watch live)")
    console.print("[2] Run in background (survives disconnect)")
    bg_choice = Prompt.ask("Mode", choices=["1", "2"], default="1", show_choices=False)
    if not Confirm.ask(f"Start farming {count} account(s) with real Chrome?", default=True):
        return
    venv_python = REPO_DIR / ".venv" / "bin" / "python"
    py = str(venv_python) if venv_python.exists() else sys.executable
    batch = str(NSCALE_SCRIPT_DIR / "batch_farm.py")
    indices = ",".join(str(i) for i, _e in chosen)
    cmd = [py, batch, "--indices", indices, "--delay", "10"]
    if bg_choice == "2":
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = f"/tmp/nscale-farm-{ts}.log"
        pidfile = Path("/tmp/nscale-farm.pid")
        farm_pid = _spawn_detached(cmd, logfile, cwd=str(REPO_DIR))
        pidfile.write_text(str(farm_pid))
        console.print(f"[green]Farm started in background (PID {farm_pid}).[/green]")
        console.print(f"[dim]Log: {logfile}[/dim]")
        console.print("[dim]Setelah batch selesai, jalankan [4] Auto inject untuk memasukkan token ke 9Router.[/dim]")
        _arm_inject_monitor(str(NSCALE_SCRIPT_DIR / "nscale_inject_monitor.py"), farm_pid, ts, "nscale", count, before_tokens)
    else:
        try:
            subprocess.run(cmd, cwd=str(REPO_DIR))
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted.[/yellow]")
        state = _load_state()
        if state.get("nscale_auto_inject", False):
            console.print("[dim]Auto-injecting to 9Router...[/dim]")
            added, skipped, err = _inject_nscale_to_9router()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]Injected: {added} new, {skipped} already there.[/green]")
        if state.get("nscale_auto_inject_omniroute", False):
            console.print("[dim]Auto-injecting to OmniRoute...[/dim]")
            added, skipped, err = _inject_nscale_to_omniroute()
            if err:
                console.print(f"[red]Inject OmniRoute failed: {err}[/red]")
            else:
                console.print(f"[green]Injected to OmniRoute: {added} new, {skipped} already there.[/green]")
    if bg_choice == "1":
        # Telegram notification, same format as TokenHarbor/GonkaRouter: only keys from THIS run.
        try:
            _after = _get_nscale_results()
            _new = [a for a in _after if a.get("service_token") and a["service_token"] not in before_tokens]
            _new_keys = [a["service_token"] for a in _new]
            _success = min(len(_new_keys), count)
            _notify_farm_done("Nscale", count, _success, count - _success,
                              _new_keys[:count],
                              emails=[a.get("email", "") for a in _new[:count]])
        except Exception:
            pass
    Prompt.ask("Press Enter to continue", default="")


def _count_nscale_running() -> int:
    """Count running Nscale batch_farm.py processes (single farm runs use the same batch script)."""
    try:
        out = subprocess.run(["pgrep", "-f", "batch_farm.py"], capture_output=True, text=True, timeout=5)
        pids = [x for x in out.stdout.strip().splitlines() if x.strip()]
        if pids:
            return len(pids)
        out = subprocess.run(["pgrep", "-f", "nscale_farm.py"], capture_output=True, text=True, timeout=5)
        return len([x for x in out.stdout.strip().splitlines() if x.strip()])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0

def menu_nscale_results():
    _clear_screen(); _nscale_header()
    console.print()
    results = _get_nscale_results()
    running = _count_nscale_running()
    try:
        total = len(_load_nscale_accounts())
    except Exception:
        total = len(results)
    if not total:
        total = len(results)
    console.print(f"[bold]Running: [cyan]{running}[/cyan] | "
                  f"[green]Success: {len(results)}[/green] | "
                  f"[dim]Total: {total}[/dim][/bold]" + chr(10))
    if results:
        t = Table(title="Nscale API keys", show_lines=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Email", style="magenta")
        t.add_column("Org", style="cyan")
        t.add_column("Credit", style="yellow")
        t.add_column("API key", style="green")
        for i, a in enumerate(results, 1):
            tok = a.get("service_token", "")
            t.add_row(str(i), str(a.get("email", "-")), str(a.get("org_name", "-")), str(a.get("credit_usd", "-")), str(a.get("service_token", "-")))
        console.print(t)
    elif not results and running == 0:
        console.print("[dim]No results yet. Run farm first.[/dim]")

    # Actions, same pattern as the other farms.
    from rich.text import Text as _Text
    console.print()
    bar = _Text()
    if results:
        bar.append("[c] ", style="bold cyan")
        bar.append("Copy all API  ")
        bar.append("[d] ", style="bold cyan")
        bar.append("Delete all results  ")
    bar.append("[Enter] ", style="bold cyan")
    bar.append("Back")
    console.print(bar)
    choices = ["c", "d", ""] if results else [""]
    action = Prompt.ask("Action", choices=choices, default="", show_choices=False)
    if action == "c" and results:
        text = chr(10).join(str(a.get("service_token", "")) for a in results)
        kf = Path("/root/nscale_keys_export.txt")
        kf.write_text(text + chr(10))
        console.print(f"[green]OK {len(results)} keys saved to {kf}[/green]")
        for a in results:
            console.print(str(a.get("service_token", "")))
        Prompt.ask(chr(10) + "Press Enter to continue", default="")
    elif action == "d" and results:
        if Confirm.ask(chr(10) + "[red]Delete ALL Nscale results?[/red]", default=False):
            _nscale_results_path().unlink(missing_ok=True)
            Path("/root/nscale_keys_export.txt").unlink(missing_ok=True)
            Path("/tmp/nscale-farm.pid").unlink(missing_ok=True)
            for log in Path("/tmp").glob("nscale-farm-*.log"):
                try:
                    log.unlink()
                except OSError:
                    pass
            console.print("[green]OK All Nscale results deleted.[/green]")
        Prompt.ask(chr(10) + "Press Enter to continue", default="")

def menu_nscale_inject_toggle():
    """Toggle auto-inject targets, same as the other farms."""
    _clear_screen()
    _menu_inject_targets("Nscale", "nscale_auto_inject", _nscale_header,
                         _inject_nscale_to_9router, _inject_nscale_to_omniroute)

def menu_nscale():
    """Nscale farm submenu."""
    while True:
        _clear_screen()
        state = _load_state()
        inject_on = state.get("nscale_auto_inject", False)
        inject_om = state.get("nscale_auto_inject_omniroute", False)
        results = _get_nscale_results()
        _nscale_header()
        console.print()
        _proxies = _get_proxies()
        _running = _count_nscale_running()
        _inject_txt = (f"9Router {'[green]ON[/green]' if inject_on else '[dim]OFF[/dim]'} · "
                      f"OmniRoute {'[green]ON[/green]' if inject_om else '[dim]OFF[/dim]'}")
        console.print(f"[dim]proxy:[/dim] {'[green]' + str(len(_proxies)) + ' set[/green]' if _proxies else '[red]not set[/red]'}   "
                      f"[dim]running:[/dim] [cyan]{_running}[/cyan]   "
                      f"[dim]keys:[/dim] [green]{len(results)}[/green]   "
                      f"[dim]auto-inject:[/dim] {_inject_txt}" + chr(10),
                      justify="center")
        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Run farm", "farm Nscale dengan Chrome asli")
        menu.add_row("[2]", "Results", f"{len(results)} akun selesai")
        menu.add_row("[3]", "Auto inject", f"9Router {("ON" if inject_on else "OFF")} · OmniRoute {("ON" if inject_om else "OFF")}")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3"], default="0", show_choices=False, show_default=False)
        if choice == "0":
            return
        if choice == "1":
            menu_nscale_run_farm()
        elif choice == "2":
            menu_nscale_results()
        elif choice == "3":
            menu_nscale_inject_toggle()

# Mistral farm submenu
# ═══════════════════════════════════════════════════════════════════════════════

def _get_mistral_keys() -> list:
    """Parse /root/mistral_keys.txt -> list of dicts."""
    if not MISTRAL_KEYS.exists():
        return []
    out = []
    for line in MISTRAL_KEYS.read_text().splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5:
            continue
        out.append({
            "email": parts[0],
            "password": parts[1],
            "session_token": parts[2],
            "status": parts[3],
            "api_key": parts[4],
            "ok": parts[3] == "KEYED",
        })
    return out


def _inject_tokenharbor_to_9router() -> tuple:
    """Inject TokenHarbor keys into 9Router SQLite. Returns (added, skipped, error)."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    _db = _9r_db_path()
    if _db is None:
        return 0, 0, "9Router is not installed on this server."
    DB = str(_db)
    PREFIX = 'HrbrFarm'
    BASE_URL = 'https://tokenharbor.ai/v1'
    NODE_NAME = 'hrbrfarm'

    def now():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    def get_accounts():
        if not RESULTS_PATH.exists():
            return []
        try:
            data = json.loads(RESULTS_PATH.read_text())
            accounts = data if isinstance(data, list) else [data]
            return [a for a in accounts if a.get("ok") and a.get("api_key")]
        except (json.JSONDecodeError, OSError):
            return []

    try:
        conn = sqlite3.connect(DB)
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"

    try:
        # Find existing node by baseUrl (reuse user's node regardless of prefix).
        node_id = None
        prefix = PREFIX
        try:
            row = conn.execute(
                "SELECT id, data FROM providerNodes WHERE json_extract(data, '$.baseUrl') = ?",
                (BASE_URL,)).fetchone()
        except Exception:
            row = None
        if row:
            node_id = row[0]
            try:
                prefix = (json.loads(row[1]) or {}).get('prefix') or PREFIX
            except Exception:
                pass
        if not node_id:
            node_id = f'openai-compatible-chat-{uuid.uuid4()}'
            data = json.dumps({'prefix': PREFIX, 'apiType': 'chat', 'baseUrl': BASE_URL, 'nodeName': NODE_NAME})
            conn.execute('INSERT INTO providerNodes (id,type,name,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?)',
                         (node_id, 'openai-compatible', NODE_NAME, data, now(), now()))
            conn.commit()

        have = set()
        try:
            for (raw,) in conn.execute('SELECT data FROM providerConnections WHERE provider=?', (node_id,)):
                try:
                    k = (json.loads(raw) or {}).get('apiKey')
                    if k:
                        have.add(k)
                except Exception:
                    pass
        except Exception:
            pass

        added = skipped = 0
        for a in get_accounts():
            key, email = a.get("api_key"), a.get("email", "")
            if not key:
                continue
            if key in have:
                skipped += 1
                continue
            n = conn.execute('SELECT COUNT(*) FROM providerConnections WHERE provider=?', (node_id,)).fetchone()[0] + 1
            data = json.dumps({
                'apiKey': key, 'authType': 'apikey', 'testStatus': 'active', 'backoffLevel': 0,
                'providerSpecificData': {'prefix': prefix, 'apiType': 'chat', 'baseUrl': BASE_URL,
                                          'nodeName': NODE_NAME, 'label': email},
            })
            conn.execute('INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (str(uuid.uuid4()), node_id, 'apikey', f'Key {n}', None, 1, 1, data, now(), now()))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def _inject_mistral_to_9router() -> tuple:
    """Inject Mistral keys into 9Router's built-in 'mistral' provider. Returns (added, skipped, error)."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    _db = _9r_db_path()
    if _db is None:
        return 0, 0, "9Router is not installed on this server."
    DB = str(_db)
    PROVIDER = 'mistral'  # built-in provider id, no custom node needed

    def now():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    try:
        conn = sqlite3.connect(DB)
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"

    try:
        have = set()
        try:
            for (raw,) in conn.execute('SELECT data FROM providerConnections WHERE provider=?', (PROVIDER,)):
                try:
                    k = (json.loads(raw) or {}).get('apiKey')
                    if k:
                        have.add(k)
                except Exception:
                    pass
        except Exception:
            pass

        added = skipped = 0
        for k in _get_mistral_keys():
            key, email = k["api_key"], k["email"]
            if not key or not k["ok"]:
                continue
            if key in have:
                skipped += 1
                continue
            n = conn.execute('SELECT COUNT(*) FROM providerConnections WHERE provider=?', (PROVIDER,)).fetchone()[0] + 1
            data = json.dumps({
                'apiKey': key, 'testStatus': 'active', 'backoffLevel': 0,
                'providerSpecificData': {'connectionProxyEnabled': False, 'connectionProxyUrl': '', 'connectionNoProxy': ''},
            })
            conn.execute('INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (str(uuid.uuid4()), PROVIDER, 'apikey', f'Key {n}', None, 1, 1, data, now(), now()))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def _count_mistral_running() -> int:
    """Count running mistral_farm.py processes."""
    try:
        out = subprocess.run(["pgrep", "-f", "mistral_farm.py"],
                             capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.strip().split("\n") if p.strip()]
        return len(pids)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0


def menu_mistral_run_farm():
    _clear_screen(); _mistral_header()
    console.print()
    _mistral_script = _resolve_script(MISTRAL_SCRIPT, "tools/tokenharbor/mistral_farm.py")
    if not _mistral_script.exists():
        console.print(f"[red]✗ Mistral farm script not found: {MISTRAL_SCRIPT}[/red]")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    proxies = _get_proxies()
    if not proxies:
        console.print("[yellow]⚠ No proxy configured.[/yellow]")
        if not Confirm.ask("Run without proxy?", default=True):
            console.print("Cancelled. Set proxies via main menu [magenta]Setup Proxy[/magenta].")
            Prompt.ask("\nPress Enter to continue", default="")
            return

    count = IntPrompt.ask("\nHow many keys to farm?", default=1)
    console.print(f"\n[dim]Proxy: {len(proxies)} (rotating)[/dim]" if proxies else "\n[dim]Proxy: none (direct)[/dim]")
    console.print(f"[dim]Script: {_mistral_script}[/dim]\n")

    if not Confirm.ask(f"Start farming {count} Mistral key(s)?", default=True):
        return

    # Snapshot existing keys BEFORE the run (for per-run notification).
    _before_keys_mistral = set(
        k.get("api_key") for k in _get_mistral_keys() if k.get("api_key")
    )

    console.print()
    console.print("[1] Run in foreground (watch live)")
    console.print("[2] Run in background (survives disconnect)")
    bg_choice = Prompt.ask("Mode", choices=["1", "2"], default="1",
                           show_choices=False)

    cmd = [sys.executable, str(_mistral_script), "--count", str(count)]
    if bg_choice == "2":
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = f"/tmp/mistral-farm-{ts}.log"
        farm_pid = _spawn_detached(cmd, logfile)
        console.print(f"[green]✓ Mistral farm started in background (PID {farm_pid}).[/green]")
        console.print(f"[dim]Log: {logfile}[/dim]")
        # Arm monitor if auto-inject ON or Telegram configured.
        state = _load_state()
        if _should_arm_monitor(state, "mistral_auto_inject") or state.get("mistral_auto_inject_omniroute", False):
            _arm_inject_monitor(str(_monitor_path("mistral")), farm_pid, ts, "mistral",
                                count, sorted(_before_keys_mistral))
    else:
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        # Auto-inject to 9Router if enabled.
        state = _load_state()
        if state.get("mistral_auto_inject", False):
            console.print("\n[dim]Auto-injecting to 9Router...[/dim]")
            added, skipped, err = _inject_mistral_to_9router()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected: {added} new, {skipped} already there.[/green]")
        if state.get("mistral_auto_inject_omniroute", False):
            console.print("\n[dim]Auto-injecting to OmniRoute...[/dim]")
            added, skipped, err = _inject_mistral_to_omniroute()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected to OmniRoute: {added} new, {skipped} already there.[/green]")
        # Telegram notification — only keys from THIS run.
        try:
            keys = _get_mistral_keys()
            new_keys = [
                k["api_key"] for k in keys
                if k.get("ok") and k.get("api_key")
                and k["api_key"] not in _before_keys_mistral
            ]
            success = min(len(new_keys), count)
            _notify_farm_done("Mistral", count, success, count - success,
                              new_keys[:count])
        except Exception:
            pass
    Prompt.ask("\nPress Enter to continue", default="")


def menu_mistral_results():
    _clear_screen(); _mistral_header()
    console.print()
    keys = _get_mistral_keys()
    ok = [k for k in keys if k["ok"]]
    running = _count_mistral_running()

    console.print(f"[bold]Running: [magenta]{running}[/magenta] | "
                  f"[green]Success: {len(ok)}[/green] | "
                  f"[dim]Total: {len(keys)}[/dim][/bold]\n")
    if ok:
        t = Table(title="Mistral API keys", show_lines=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Email", style="magenta")
        t.add_column("API key", style="green")
        for i, k in enumerate(ok, 1):
            t.add_row(str(i), k["email"], k["api_key"])
        console.print(t)
    elif not keys and running == 0:
        console.print("[dim]No results yet. Run farm first.[/dim]")

    # Actions
    from rich.text import Text as _Text
    console.print()
    bar = _Text()
    if ok:
        bar.append("[c] ", style="bold magenta")
        bar.append("Copy all API  ")
        bar.append("[d] ", style="bold magenta")
        bar.append("Delete all results  ")
    bar.append("[Enter] ", style="bold magenta")
    bar.append("Back")
    console.print(bar)
    choices = ["c", "d", ""] if ok else [""]
    action = Prompt.ask("Action", choices=choices, default="", show_choices=False)
    if action == "c" and ok:
        text = "\n".join(k["api_key"] for k in ok)
        kf = Path("/root/mistral_keys_export.txt")
        kf.write_text(text + "\n")
        console.print(f"[green]✓ {len(ok)} keys saved to {kf}[/green]")
        for k in ok:
            console.print(f"  {k['api_key']}")
        Prompt.ask("\nPress Enter to continue", default="")
    elif action == "d" and ok:
        if Confirm.ask("\n[red]Delete ALL Mistral results?[/red]", default=False):
            MISTRAL_KEYS.unlink(missing_ok=True)
            kf = Path("/root/mistral_keys_export.txt")
            kf.unlink(missing_ok=True)
            for log in Path("/tmp").glob("mistral-farm-*.log"):
                try:
                    log.unlink()
                except OSError:
                    pass
            console.print("[green]✓ All Mistral results deleted.[/green]")
        Prompt.ask("\nPress Enter to continue", default="")


def menu_mistral():
    """Mistral farm submenu."""
    while True:
        _clear_screen()
        _mistral_header()
        console.print()
        proxies = _get_proxies()
        running = _count_mistral_running()
        keys = _get_mistral_keys()
        ok = len([k for k in keys if k["ok"]])
        state = _load_state()
        inject_on = state.get("mistral_auto_inject", False)
        inject_om = state.get("mistral_auto_inject_omniroute", False)
        inject_txt = (f"9Router {'[green]ON[/green]' if inject_on else '[dim]OFF[/dim]'} · "
                      f"OmniRoute {'[green]ON[/green]' if inject_om else '[dim]OFF[/dim]'}")

        console.print(f"[dim]proxy:[/dim] {'[green]' + str(len(proxies)) + ' set[/green]' if proxies else '[red]not set[/red]'}   "
                      f"[dim]running:[/dim] [magenta]{running}[/magenta]   "
                      f"[dim]keys:[/dim] [green]{ok}[/green]   "
                      f"[dim]auto-inject:[/dim] {inject_txt}\n",
                      justify="center")

        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", style="bold bright_magenta", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Run farm", "farm Mistral API keys")
        menu.add_row("[2]", "Results", f"{ok} keys farmed")
        menu.add_row("[3]", "Auto inject", f"9Router {('ON' if inject_on else 'OFF')} · OmniRoute {('ON' if inject_om else 'OFF')}")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3"],
                            default="1", show_choices=False, show_default=False)
        if choice == "1":
            menu_mistral_run_farm()
        elif choice == "2":
            menu_mistral_results()
        elif choice == "3":
            menu_mistral_inject_toggle()
        else:
            return


def _9r_db_candidates() -> list:
    """Candidate data.sqlite locations for a local 9Router install."""
    cands = []
    env = os.environ.get("NINEROUTER_DB_PATH")
    if env:
        cands.append(Path(env))
    cands += [
        # npm global install (default: data under the user's home)
        Path.home() / ".9router" / "db" / "data.sqlite",
        # installs with a system data dir
        Path("/var/lib/9router/db/data.sqlite"),
    ]
    return cands


def _9r_db_path():
    """Return the 9Router data.sqlite path, or None if not installed."""
    for p in _9r_db_candidates():
        if p.exists():
            return p
    return None


def _check_9router() -> tuple:
    """Check if 9Router is installed. Returns (ok: bool, msg: str)."""
    db = _9r_db_path()
    if db is None:
        return False, "9Router is not installed on this server."
    # Verify the expected tables exist.
    try:
        import sqlite3
        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        if 'providerNodes' not in tables or 'providerConnections' not in tables:
            return False, "9Router DB found but schema is incomplete."
        return True, f"9Router detected ({db})."
    except Exception as e:
        return False, f"9Router DB check failed: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# OmniRoute inject — target kedua selain 9Router.
#
# OmniRoute (fork 9Router) menyimpan data di storage.sqlite dengan tabel
# snake_case (provider_nodes / provider_connections) dan kolom asli, BUKAN
# JSON blob. Perbedaan krusial: api_key TERENKRIPSI format
# "enc:v1:<iv_hex>:<ciphertext_hex>:<authtag_hex>" (AES-256-GCM, IV 16 byte,
# auth tag 16 byte). Kunci diturunkan dari STORAGE_ENCRYPTION_KEY via
# scrypt (salt tetap "omniroute-field-encryption-v1", N=16384 r=8 p=1,
# 32 byte) — skema dibaca dari bundle OmniRoute dan terbukti round-trip.
# Bila install OmniRoute tanpa STORAGE_ENCRYPTION_KEY, aplikasinya sendiri
# menyimpan plaintext (passthrough) — injector ikut menyimpan plaintext.
# ═══════════════════════════════════════════════════════════════════════════════

_OMNI_SCRYPT_SALT = b"omniroute-field-encryption-v1"
_omni_aes_cache = {}


def _omni_db_candidates() -> list:
    """Candidate storage.sqlite locations for a local OmniRoute install."""
    cands = []
    env = os.environ.get("OMNIROUTE_DB_PATH")
    if env:
        cands.append(Path(env))
    cands += [
        # Docker named volume (install Docker seperti di VPS ini)
        Path("/var/lib/docker/volumes/omniroute-data/_data/storage.sqlite"),
        # Native / data-dir installs
        Path.home() / ".omniroute" / "storage.sqlite",
        Path("/app/data/storage.sqlite"),
    ]
    return cands


def _omni_db_path():
    """Return the OmniRoute storage.sqlite path, or None if not installed."""
    for p in _omni_db_candidates():
        if p.exists():
            return p
    import glob as _glob
    for hit in sorted(_glob.glob(
            "/var/lib/docker/volumes/*omniroute*/_data/storage.sqlite")):
        return Path(hit)
    return None


def _check_omniroute() -> tuple:
    """Check if OmniRoute is installed on this server. Returns (ok, msg)."""
    db = _omni_db_path()
    if db is None:
        return False, "OmniRoute is not installed on this server."
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        if 'provider_nodes' not in tables or 'provider_connections' not in tables:
            return False, "OmniRoute DB found but schema is incomplete."
        return True, f"OmniRoute detected ({db})."
    except Exception as e:
        return False, f"OmniRoute DB check failed: {e}"


def _omni_storage_key():
    """Find the STORAGE_ENCRYPTION_KEY of the local OmniRoute install."""
    for var in ("OMNIROUTE_STORAGE_ENCRYPTION_KEY", "STORAGE_ENCRYPTION_KEY"):
        v = os.environ.get(var)
        if v and v.strip():
            return v.strip()
    for env_file in (Path("/opt/omniroute/.env"),
                     Path.home() / ".omniroute" / ".env",
                     Path("/app/data/server.env")):
        try:
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("STORAGE_ENCRYPTION_KEY="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except Exception:
            pass
    # Docker install: baca env container-nya langsung.
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format",
             "{{range .Config.Env}}{{println .}}{{end}}", "omniroute"],
            capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if line.startswith("STORAGE_ENCRYPTION_KEY="):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    except Exception:
        pass
    return None


def _omni_aes():
    """AESGCM instance keyed for this OmniRoute install, or None."""
    sek = _omni_storage_key()
    if not sek:
        return None
    if sek in _omni_aes_cache:
        return _omni_aes_cache[sek]
    import hashlib
    key = hashlib.scrypt(sek.encode(), salt=_OMNI_SCRYPT_SALT,
                         n=16384, r=8, p=1, dklen=32,
                         maxmem=64 * 1024 * 1024)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aes = AESGCM(key)
    _omni_aes_cache[sek] = aes
    return aes


def _omni_encrypt(plaintext: str, aes) -> str:
    """Encrypt exactly like OmniRoute: enc:v1:<iv_hex>:<ct_hex>:<tag_hex>."""
    iv = os.urandom(16)
    out = aes.encrypt(iv, plaintext.encode(), None)
    ct, tag = out[:-16], out[-16:]
    return f"enc:v1:{iv.hex()}:{ct.hex()}:{tag.hex()}"


def _omni_decrypt(value, aes):
    """Decrypt an OmniRoute enc:v1 value; passthrough plaintext; None on failure.

    aes=None means this OmniRoute install has no STORAGE_ENCRYPTION_KEY,
    so the app itself stores plaintext — nothing to decrypt.
    """
    if not value or not isinstance(value, str):
        return value
    if not value.startswith("enc:v1:"):
        return value
    if aes is None:
        return value
    try:
        iv_hex, ct_hex, tag_hex = value[len("enc:v1:"):].split(":")
        data = bytes.fromhex(ct_hex) + bytes.fromhex(tag_hex)
        return aes.decrypt(bytes.fromhex(iv_hex), data, None).decode()
    except Exception:
        return None


def _omni_now() -> str:
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"


def _restart_omniroute(db_path) -> None:
    """Best-effort container restart so OmniRoute reloads new connections."""
    try:
        if "docker/volumes" not in str(db_path):
            return
        subprocess.run(["docker", "restart", "omniroute"],
                       capture_output=True, timeout=120)
    except Exception:
        pass


def _inject_entries_to_omniroute(entries, builtin=None, node=None) -> tuple:
    """Generic OmniRoute injector. Returns (added, skipped, error).

    entries: list of {'api_key': str, 'label': str, 'psd': dict|None}
    builtin: built-in provider id ('dahl' / 'mistral'), no node needed.
    node:    {'base_url', 'prefix', 'name'} for openai-compatible nodes —
             the node is reused by base_url when it already exists.
    """
    import sqlite3, uuid
    db = _omni_db_path()
    if db is None:
        return 0, 0, "OmniRoute DB not found on this server."
    # aes=None = OmniRoute tanpa STORAGE_ENCRYPTION_KEY: aplikasinya sendiri
    # menyimpan plaintext (passthrough), jadi kita ikut menyimpan plaintext.
    aes = _omni_aes()
    try:
        conn = sqlite3.connect(str(db), timeout=30)
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        if node:
            row = conn.execute(
                "SELECT id, prefix, name FROM provider_nodes "
                "WHERE base_url=? LIMIT 1", (node["base_url"],)).fetchone()
            if row:
                provider_id, prefix, node_name = row
            else:
                provider_id = 'openai-compatible-chat-' + str(uuid.uuid4())
                prefix, node_name = node["prefix"], node["name"]
                now = _omni_now()
                conn.execute(
                    "INSERT INTO provider_nodes"
                    " (id,type,name,prefix,api_type,base_url,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (provider_id, 'openai-compatible', node_name, prefix,
                     'chat', node["base_url"], now, now))
                conn.commit()
        else:
            provider_id, prefix, node_name = builtin, None, None

        # Dedupe: existing api_keys are encrypted — decrypt to compare.
        have = set()
        for (raw,) in conn.execute(
                "SELECT api_key FROM provider_connections WHERE provider=?",
                (provider_id,)):
            plain = _omni_decrypt(raw, aes)
            if plain:
                have.add(plain)

        added = skipped = 0
        for e in entries:
            key = e.get("api_key")
            if not key:
                continue
            if key in have:
                skipped += 1
                continue
            n = conn.execute(
                "SELECT COUNT(*) FROM provider_connections WHERE provider=?",
                (provider_id,)).fetchone()[0] + 1
            if node:
                psd = {'prefix': prefix, 'apiType': 'chat',
                       'baseUrl': node["base_url"], 'nodeName': node_name,
                       'label': e.get("label") or ''}
            else:
                psd = dict(e.get("psd") or {})
            now = _omni_now()
            conn.execute(
                "INSERT INTO provider_connections"
                " (id,provider,auth_type,name,email,priority,is_active,api_key,"
                " test_status,backoff_level,provider_specific_data,"
                " proxy_enabled,per_key_proxy_enabled,quota_visible,"
                " rate_limit_protection,consecutive_use_count,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), provider_id, 'apikey', f'Key {n}', None,
                 1, 1, (_omni_encrypt(key, aes) if aes else key), 'active', 0,
                 json.dumps(psd), 1, 0, 1, 0, 0, now, now))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        if added:
            _restart_omniroute(db)
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def _inject_tokenharbor_to_omniroute() -> tuple:
    """Inject TokenHarbor keys into OmniRoute custom node. Returns (added, skipped, error)."""
    if not RESULTS_PATH.exists():
        return 0, 0, None
    try:
        data = json.loads(RESULTS_PATH.read_text())
        accounts = data if isinstance(data, list) else [data]
    except (json.JSONDecodeError, OSError):
        accounts = []
    entries = [{'api_key': a.get("api_key"), 'label': a.get("email", "")}
               for a in accounts if a.get("ok") and a.get("api_key")]
    return _inject_entries_to_omniroute(
        entries, node={'base_url': 'https://tokenharbor.ai/v1',
                        'prefix': 'HrbrFarm', 'name': 'hrbrfarm'})


def _inject_mistral_to_omniroute() -> tuple:
    """Inject Mistral keys into OmniRoute's built-in 'mistral' provider. Returns (added, skipped, error)."""
    entries = [{'api_key': k["api_key"], 'label': k["email"],
                'psd': {'connectionProxyEnabled': False, 'connectionProxyUrl': '',
                        'connectionNoProxy': ''}}
               for k in _get_mistral_keys() if k.get("ok") and k.get("api_key")]
    return _inject_entries_to_omniroute(entries, builtin='mistral')


def _inject_dahl_to_omniroute() -> tuple:
    """Inject Dahl keys into OmniRoute's built-in 'dahl' provider. Returns (added, skipped, error)."""
    entries = [{'api_key': k["api_key"], 'label': k["username"],
                'psd': {'connectionProxyEnabled': False, 'connectionProxyUrl': '',
                        'connectionNoProxy': ''}}
               for k in _get_dahl_keys() if k.get("ok") and k.get("api_key")]
    return _inject_entries_to_omniroute(entries, builtin='dahl')


def _inject_gonka_to_omniroute() -> tuple:
    """Inject GonkaRouter keys into OmniRoute custom node. Returns (added, skipped, error)."""
    entries = [{'api_key': k["api_key"], 'label': k["address"]}
               for k in _get_gonka_keys() if k.get("ok") and k.get("api_key")]
    return _inject_entries_to_omniroute(
        entries, node={'base_url': 'https://api.gonkarouter.io/v1',
                        'prefix': 'gofarm', 'name': 'gonkarouter'})


def _menu_inject_targets(provider_label, state_key, header_fn,
                         inject_9r, inject_omni):
    """Toggle auto-inject targets: 9Router, OmniRoute, atau keduanya."""
    header_fn()
    console.print()
    state = _load_state()
    omni_key = state_key + "_omniroute"
    cur_9r = state.get(state_key, False)
    cur_om = state.get(omni_key, False)

    def txt(v):
        return "[green]ON[/green]" if v else "[dim]OFF[/dim]"

    console.print(f"\nAuto inject targets for {provider_label}:")
    console.print(f"  9Router:   {txt(cur_9r)}")
    console.print(f"  OmniRoute: {txt(cur_om)}")
    console.print("[dim]Keys are injected to every target that is ON "
                  "(both can be ON).[/dim]\n")
    console.print(f"[1] Turn {'OFF' if cur_9r else 'ON'} 9Router")
    console.print(f"[2] Turn {'OFF' if cur_om else 'ON'} OmniRoute")
    console.print("[0] Back\n")
    choice = Prompt.ask("Select", choices=["0", "1", "2"], default="0",
                        show_choices=False)
    if choice == "1":
        if cur_9r:
            state[state_key] = False
            _save_state(state)
            console.print("\n[dim]Auto inject 9Router: OFF[/dim]")
        else:
            ok, msg = _check_9router()
            if not ok:
                console.print(f"\n[red]✗ {msg}[/red]")
                Prompt.ask("\nPress Enter to continue", default="")
                return
            console.print(f"\n[dim]✓ {msg}[/dim]")
            state[state_key] = True
            _save_state(state)
            console.print("[green]✓ Auto inject 9Router: ON[/green]")
            added, skipped, err = inject_9r()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[dim]Injected now: {added} added, {skipped} already there.[/dim]")
    elif choice == "2":
        if cur_om:
            state[omni_key] = False
            _save_state(state)
            console.print("\n[dim]Auto inject OmniRoute: OFF[/dim]")
        else:
            ok, msg = _check_omniroute()
            if not ok:
                console.print(f"\n[red]✗ {msg}[/red]")
                Prompt.ask("\nPress Enter to continue", default="")
                return
            console.print(f"\n[dim]✓ {msg}[/dim]")
            state[omni_key] = True
            _save_state(state)
            console.print("[green]✓ Auto inject OmniRoute: ON[/green]")
            added, skipped, err = inject_omni()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[dim]Injected now: {added} added, {skipped} already there.[/dim]")
    Prompt.ask("\nPress Enter to continue", default="")


def menu_tokenharbor_inject_toggle():
    _clear_screen()
    _menu_inject_targets("TokenHarbor", "tokenharbor_auto_inject",
                         _harbor_header, _inject_tokenharbor_to_9router,
                         _inject_tokenharbor_to_omniroute)


def menu_mistral_inject_toggle():
    _clear_screen()
    _menu_inject_targets("Mistral", "mistral_auto_inject",
                         _mistral_header, _inject_mistral_to_9router,
                         _inject_mistral_to_omniroute)


# ═══════════════════════════════════════════════════════════════════════════════
# Dahl farm
# ═══════════════════════════════════════════════════════════════════════════════

def _get_dahl_keys() -> list:
    """Parse /root/dahl_keys.txt -> list of dicts."""
    if not DAHL_KEYS.exists():
        return []
    out = []
    for line in DAHL_KEYS.read_text().splitlines():
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue
        out.append({
            "username": parts[0],
            "fingerprint": parts[1],
            "status": parts[2],
            "api_key": parts[3],
            "ok": parts[2] == "ok",
        })
    return out


def _count_dahl_running() -> int:
    count = 0
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmd = (proc / "cmdline").read_text()
                if "dahl_farm.py" in cmd and "inject_monitor" not in cmd:
                    count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count


def _inject_dahl_to_9router() -> tuple:
    """Inject Dahl keys into 9Router's built-in 'dahl' provider. Returns (added, skipped, error)."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    _db = _9r_db_path()
    if _db is None:
        return 0, 0, "9Router is not installed on this server."
    DB = str(_db)
    PROVIDER = 'dahl'  # built-in provider id, no custom node needed

    def now():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    try:
        conn = sqlite3.connect(DB)
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"

    try:
        have = set()
        try:
            for (raw,) in conn.execute('SELECT data FROM providerConnections WHERE provider=?', (PROVIDER,)):
                try:
                    k = (json.loads(raw) or {}).get('apiKey')
                    if k:
                        have.add(k)
                except Exception:
                    pass
        except Exception:
            pass

        added = skipped = 0
        for k in _get_dahl_keys():
            key, username = k["api_key"], k["username"]
            if not key or not k["ok"]:
                continue
            if key in have:
                skipped += 1
                continue
            n = conn.execute('SELECT COUNT(*) FROM providerConnections WHERE provider=?', (PROVIDER,)).fetchone()[0] + 1
            data = json.dumps({
                'apiKey': key, 'testStatus': 'active', 'backoffLevel': 0,
                'providerSpecificData': {'connectionProxyEnabled': False, 'connectionProxyUrl': '', 'connectionNoProxy': ''},
            })
            conn.execute('INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (str(uuid.uuid4()), PROVIDER, 'apikey', f'Key {n}', None, 1, 1, data, now(), now()))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def menu_dahl_run_farm():
    _clear_screen(); _dahl_header()
    console.print()
    _dahl_script = _resolve_script(DAHL_SCRIPT, "tools/tokenharbor/dahl_farm.py")
    if not _dahl_script.exists():
        console.print(f"[red]✗ Dahl farm script not found: {DAHL_SCRIPT}[/red]")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    count = IntPrompt.ask("\nHow many keys to farm?", default=1)
    console.print(f"\n[dim]Script: {_dahl_script}[/dim]")
    console.print("[dim]Pure HTTP — no browser, no email, no captcha.[/dim]\n")

    if not Confirm.ask(f"Start farming {count} Dahl key(s)?", default=True):
        return

    # Snapshot existing keys BEFORE the run (for per-run notification).
    _before_keys_dahl = set(
        k.get("api_key") for k in _get_dahl_keys() if k.get("api_key")
    )

    console.print()
    console.print("[1] Run in foreground (watch live)")
    console.print("[2] Run in background (survives disconnect)")
    bg_choice = Prompt.ask("Mode", choices=["1", "2"], default="1",
                           show_choices=False)

    cmd = [sys.executable, str(_dahl_script), "--count", str(count)]
    if bg_choice == "2":
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = f"/tmp/dahl-farm-{ts}.log"
        farm_pid = _spawn_detached(cmd, logfile)
        console.print(f"[green]✓ Dahl farm started in background (PID {farm_pid}).[/green]")
        console.print(f"[dim]Log: {logfile}[/dim]")
        # Arm monitor if auto-inject ON or Telegram configured.
        state = _load_state()
        if _should_arm_monitor(state, "dahl_auto_inject") or state.get("dahl_auto_inject_omniroute", False):
            _arm_inject_monitor(str(_monitor_path("dahl")), farm_pid, ts, "dahl",
                                count, sorted(_before_keys_dahl))
    else:
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        # Auto-inject to 9Router if enabled.
        state = _load_state()
        if state.get("dahl_auto_inject", False):
            console.print("\n[dim]Auto-injecting to 9Router...[/dim]")
            added, skipped, err = _inject_dahl_to_9router()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected: {added} new, {skipped} already there.[/green]")
        if state.get("dahl_auto_inject_omniroute", False):
            console.print("\n[dim]Auto-injecting to OmniRoute...[/dim]")
            added, skipped, err = _inject_dahl_to_omniroute()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected to OmniRoute: {added} new, {skipped} already there.[/green]")
        # Telegram notification — only keys from THIS run.
        try:
            keys = _get_dahl_keys()
            new_keys = [
                k["api_key"] for k in keys
                if k.get("ok") and k.get("api_key")
                and k["api_key"] not in _before_keys_dahl
            ]
            success = min(len(new_keys), count)
            _notify_farm_done("Dahl", count, success, count - success,
                              new_keys[:count])
        except Exception:
            pass
    Prompt.ask("\nPress Enter to continue", default="")


def menu_dahl_results():
    _clear_screen(); _dahl_header()
    console.print()
    keys = _get_dahl_keys()
    ok = [k for k in keys if k["ok"]]
    running = _count_dahl_running()

    console.print(f"[bold]Running: [green]{running}[/green] | "
                  f"[green]Success: {len(ok)}[/green] | "
                  f"[dim]Total: {len(keys)}[/dim][/bold]\n",
                  justify="center")
    if ok:
        t = Table(title="Dahl API keys", show_lines=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Username", style="green")
        t.add_column("API key", style="green")
        for i, k in enumerate(ok, 1):
            t.add_row(str(i), k["username"], k["api_key"])
        console.print(t)
    elif not keys and running == 0:
        console.print("[dim]No results yet. Run farm first.[/dim]")

    from rich.text import Text as _Text
    console.print()
    bar = _Text()
    if ok:
        bar.append("[c] ", style="bold green")
        bar.append("Copy all API  ")
        bar.append("[d] ", style="bold green")
        bar.append("Delete all results  ")
    bar.append("[Enter] ", style="bold green")
    bar.append("Back")
    console.print(bar)
    choices = ["c", "d", ""] if ok else [""]
    action = Prompt.ask("Action", choices=choices, default="", show_choices=False)
    if action == "c" and ok:
        text = "\n".join(k["api_key"] for k in ok)
        kf = Path("/root/dahl_keys_export.txt")
        kf.write_text(text + "\n")
        console.print(f"[green]✓ {len(ok)} keys saved to {kf}[/green]")
        for k in ok:
            console.print(f"  {k['api_key']}")
        Prompt.ask("\nPress Enter to continue", default="")
    elif action == "d" and ok:
        if Confirm.ask("\n[red]Delete ALL Dahl results?[/red]", default=False):
            DAHL_KEYS.unlink(missing_ok=True)
            kf = Path("/root/dahl_keys_export.txt")
            kf.unlink(missing_ok=True)
            for log in Path("/tmp").glob("dahl-farm-*.log"):
                try:
                    log.unlink()
                except OSError:
                    pass
            console.print("[green]✓ All Dahl results deleted.[/green]")
        Prompt.ask("\nPress Enter to continue", default="")


def menu_dahl_inject_toggle():
    _clear_screen()
    _menu_inject_targets("Dahl", "dahl_auto_inject",
                         _dahl_header, _inject_dahl_to_9router,
                         _inject_dahl_to_omniroute)


def menu_dahl():
    """Dahl farm submenu."""
    while True:
        _clear_screen()
        _dahl_header()
        console.print()
        running = _count_dahl_running()
        keys = _get_dahl_keys()
        ok = len([k for k in keys if k["ok"]])
        state = _load_state()
        inject_on = state.get("dahl_auto_inject", False)
        inject_om = state.get("dahl_auto_inject_omniroute", False)
        inject_txt = (f"9Router {'[green]ON[/green]' if inject_on else '[dim]OFF[/dim]'} · "
                      f"OmniRoute {'[green]ON[/green]' if inject_om else '[dim]OFF[/dim]'}")

        console.print(f"[dim]running:[/dim] [green]{running}[/green]   "
                      f"[dim]keys:[/dim] [green]{ok}[/green]   "
                      f"[dim]auto-inject:[/dim] {inject_txt}\n",
                      justify="center")

        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", style="bold bright_green", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Run farm", "farm Dahl API keys")
        menu.add_row("[2]", "Results", f"{ok} keys farmed")
        menu.add_row("[3]", "Auto inject", f"9Router {('ON' if inject_on else 'OFF')} · OmniRoute {('ON' if inject_om else 'OFF')}")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3"],
                            default="1", show_choices=False, show_default=False)
        if choice == "1":
            menu_dahl_run_farm()
        elif choice == "2":
            menu_dahl_results()
        elif choice == "3":
            menu_dahl_inject_toggle()
        else:
            return


# ═══════════════════════════════════════════════════════════════════════════════
# GonkaRouter
# ═══════════════════════════════════════════════════════════════════════════════

def _get_gonka_keys() -> list:
    """Parse /root/gonka_keys.txt -> list of dicts."""
    if not GONKA_KEYS.exists():
        return []
    out = []
    for line in GONKA_KEYS.read_text().splitlines():
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue
        out.append({
            "address": parts[0],
            "user_id": parts[1],
            "status": parts[2],
            "api_key": parts[3],
            "ok": parts[2] == "ok",
        })
    return out


def _count_gonka_running() -> int:
    count = 0
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmd = (proc / "cmdline").read_text()
                if "gonka_farm" in cmd and "inject_monitor" not in cmd:
                    count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count


def _inject_gonka_to_9router() -> tuple:
    """Inject GonkaRouter keys into 9Router custom node. Returns (added, skipped, error)."""
    import sqlite3, uuid
    from datetime import datetime, timezone
    _db = _9r_db_path()
    if _db is None:
        return 0, 0, "9Router is not installed on this server."
    DB = str(_db)
    PREFIX = 'gofarm'
    BASE_URL = 'https://api.gonkarouter.io/v1'
    NODE_NAME = 'gonkarouter'

    def now():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    try:
        conn = sqlite3.connect(DB)
    except Exception as e:
        return 0, 0, f"DB open failed: {e}"

    try:
        # Find existing node by baseUrl (reuse user's node regardless of prefix).
        node_id = None
        prefix = PREFIX
        try:
            row = conn.execute(
                "SELECT id, data FROM providerNodes WHERE json_extract(data, '$.baseUrl') = ?",
                (BASE_URL,)).fetchone()
        except Exception:
            row = None
        if row:
            node_id = row[0]
            try:
                prefix = (json.loads(row[1]) or {}).get('prefix') or PREFIX
            except Exception:
                pass
        if not node_id:
            node_id = f'openai-compatible-chat-{uuid.uuid4()}'
            data = json.dumps({'prefix': PREFIX, 'apiType': 'chat', 'baseUrl': BASE_URL, 'nodeName': NODE_NAME})
            conn.execute('INSERT INTO providerNodes (id,type,name,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?)',
                         (node_id, 'openai-compatible', NODE_NAME, data, now(), now()))
            conn.commit()

        have = set()
        try:
            for (raw,) in conn.execute('SELECT data FROM providerConnections WHERE provider=?', (node_id,)):
                try:
                    k = (json.loads(raw) or {}).get('apiKey')
                    if k:
                        have.add(k)
                except Exception:
                    pass
        except Exception:
            pass

        added = skipped = 0
        for k in _get_gonka_keys():
            key, address = k["api_key"], k["address"]
            if not key or not k["ok"]:
                continue
            if key in have:
                skipped += 1
                continue
            n = conn.execute('SELECT COUNT(*) FROM providerConnections WHERE provider=?', (node_id,)).fetchone()[0] + 1
            data = json.dumps({
                'apiKey': key, 'authType': 'apikey', 'testStatus': 'active', 'backoffLevel': 0,
                'providerSpecificData': {'prefix': prefix, 'apiType': 'chat', 'baseUrl': BASE_URL,
                                          'nodeName': NODE_NAME, 'label': address},
            })
            conn.execute('INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (str(uuid.uuid4()), node_id, 'apikey', f'Key {n}', None, 1, 1, data, now(), now()))
            conn.commit()
            have.add(key)
            added += 1
        conn.close()
        return added, skipped, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return 0, 0, str(e)


def menu_gonka_run_farm():
    _clear_screen(); _gonka_header()
    console.print()
    _gonka_script = _resolve_script(GONKA_SCRIPT, "tools/tokenharbor/gonka_farm_email.py")
    if not _gonka_script.exists():
        console.print(f"[red]✗ GonkaRouter farm script not found: {GONKA_SCRIPT}[/red]")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    count = IntPrompt.ask("\nHow many keys to farm?", default=1)
    console.print(f"\n[dim]Script: {_gonka_script}[/dim]")
    console.print("[dim]Email + OTP — Turnstile solved via Capsolver.[/dim]\n")

    if not Confirm.ask(f"Start farming {count} GonkaRouter key(s)?", default=True):
        return

    # Snapshot existing keys BEFORE the run (for per-run notification).
    _before_keys_gonka = set(
        k.get("api_key") for k in _get_gonka_keys() if k.get("api_key")
    )

    console.print()
    console.print("[1] Run in foreground (watch live)")
    console.print("[2] Run in background (survives disconnect)")
    bg_choice = Prompt.ask("Mode", choices=["1", "2"], default="1",
                           show_choices=False)

    cmd = [sys.executable, str(_gonka_script), "--count", str(count),
                     "--out", str(GONKA_KEYS)]
    if bg_choice == "2":
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        logfile = f"/tmp/gonka-farm-{ts}.log"
        farm_pid = _spawn_detached(cmd, logfile)
        console.print(f"[green]✓ GonkaRouter farm started in background (PID {farm_pid}).[/green]")
        console.print(f"[dim]Log: {logfile}[/dim]")
        # Arm monitor if auto-inject ON or Telegram configured.
        state = _load_state()
        if _should_arm_monitor(state, "gonka_auto_inject") or state.get("gonka_auto_inject_omniroute", False):
            _arm_inject_monitor(str(_monitor_path("gonka")), farm_pid, ts, "gonka",
                                count, sorted(_before_keys_gonka))
    else:
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        # Auto-inject to 9Router if enabled.
        state = _load_state()
        if state.get("gonka_auto_inject", False):
            console.print("\n[dim]Auto-injecting to 9Router...[/dim]")
            added, skipped, err = _inject_gonka_to_9router()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected: {added} new, {skipped} already there.[/green]")
        if state.get("gonka_auto_inject_omniroute", False):
            console.print("\n[dim]Auto-injecting to OmniRoute...[/dim]")
            added, skipped, err = _inject_gonka_to_omniroute()
            if err:
                console.print(f"[red]Inject failed: {err}[/red]")
            else:
                console.print(f"[green]✓ Injected to OmniRoute: {added} new, {skipped} already there.[/green]")
        # Telegram notification — only keys from THIS run.
        try:
            keys = _get_gonka_keys()
            new = [k for k in keys
                   if k.get("ok") and k.get("api_key")
                   and k["api_key"] not in _before_keys_gonka]
            new_keys = [k["api_key"] for k in new]
            success = min(len(new_keys), count)
            _notify_farm_done("GonkaRouter", count, success, count - success,
                              new_keys[:count],
                              emails=[k["address"] for k in new[:count]])
        except Exception:
            pass
    Prompt.ask("\nPress Enter to continue", default="")


def menu_gonka_results():
    _clear_screen(); _gonka_header()
    console.print()
    keys = _get_gonka_keys()
    ok = [k for k in keys if k["ok"]]
    running = _count_gonka_running()

    console.print(f"[bold]Running: [green]{running}[/green] | "
                  f"[green]Success: {len(ok)}[/green] | "
                  f"[dim]Total: {len(keys)}[/dim][/bold]\n",
                  justify="center")
    if ok:
        t = Table(title="GonkaRouter API keys", show_lines=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Address", style="cyan")
        t.add_column("API key", style="green")
        for i, k in enumerate(ok, 1):
            t.add_row(str(i), k["address"][:18] + "...", k["api_key"])
        console.print(t)
    elif not keys and running == 0:
        console.print("[dim]No results yet. Run farm first.[/dim]")

    from rich.text import Text as _Text
    console.print()
    bar = _Text()
    if ok:
        bar.append("[c] ", style="bold green")
        bar.append("Copy all API  ")
        bar.append("[d] ", style="bold green")
        bar.append("Delete all results  ")
    bar.append("[Enter] ", style="bold green")
    bar.append("Back")
    console.print(bar)
    choices = ["c", "d", ""] if ok else [""]
    action = Prompt.ask("Action", choices=choices, default="", show_choices=False)
    if action == "c" and ok:
        text = "\n".join(k["api_key"] for k in ok)
        kf = Path("/root/gonka_keys_export.txt")
        kf.write_text(text + "\n")
        console.print(f"[green]✓ {len(ok)} keys saved to {kf}[/green]")
        for k in ok:
            console.print(f"  {k['api_key']}")
        Prompt.ask("\nPress Enter to continue", default="")
    elif action == "d" and ok:
        if Confirm.ask("\n[red]Delete ALL GonkaRouter results?[/red]", default=False):
            GONKA_KEYS.unlink(missing_ok=True)
            kf = Path("/root/gonka_keys_export.txt")
            kf.unlink(missing_ok=True)
            for log in Path("/tmp").glob("gonka-farm-*.log"):
                try:
                    log.unlink()
                except OSError:
                    pass
            console.print("[green]✓ All GonkaRouter results deleted.[/green]")
        Prompt.ask("\nPress Enter to continue", default="")


def menu_gonka_inject_toggle():
    _clear_screen()
    _menu_inject_targets("GonkaRouter", "gonka_auto_inject",
                         _gonka_header, _inject_gonka_to_9router,
                         _inject_gonka_to_omniroute)


def menu_gonka():
    """GonkaRouter farm submenu."""
    while True:
        _clear_screen()
        _gonka_header()
        console.print()
        running = _count_gonka_running()
        keys = _get_gonka_keys()
        ok = len([k for k in keys if k["ok"]])
        state = _load_state()
        inject_on = state.get("gonka_auto_inject", False)
        inject_om = state.get("gonka_auto_inject_omniroute", False)
        inject_txt = (f"9Router {'[green]ON[/green]' if inject_on else '[dim]OFF[/dim]'} · "
                      f"OmniRoute {'[green]ON[/green]' if inject_om else '[dim]OFF[/dim]'}")

        console.print(f"[dim]running:[/dim] [green]{running}[/green]   "
                      f"[dim]keys:[/dim] [green]{ok}[/green]   "
                      f"[dim]auto-inject:[/dim] {inject_txt}\n",
                      justify="center")

        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", style="bold white", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        menu.add_row("[1]", "Run farm", "farm GonkaRouter API keys (email + OTP)")
        menu.add_row("[2]", "Results", f"{ok} keys farmed")
        menu.add_row("[3]", "Auto inject", f"9Router {('ON' if inject_on else 'OFF')} · OmniRoute {('ON' if inject_om else 'OFF')}")
        menu.add_row("[0]", "Back", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3"],
                            default="1", show_choices=False, show_default=False)
        if choice == "1":
            menu_gonka_run_farm()
        elif choice == "2":
            menu_gonka_results()
        elif choice == "3":
            menu_gonka_inject_toggle()
        else:
            return


# ═══════════════════════════════════════════════════════════════════════════════
# Parallel farm
# ═══════════════════════════════════════════════════════════════════════════════


def _should_arm_monitor(state: dict, inject_key: str) -> bool:
    """Arm monitor if auto-inject is ON or Telegram is configured."""
    if state.get(inject_key, False):
        return True
    return bool(state.get("telegram_bot_token") and state.get("telegram_chat_id"))


def _spawn_detached(cmd: list, logfile: str, cwd: str = None) -> int:
    """Spawn a fully detached process via double-fork. Returns grandchild PID.
    The process is adopted by init, so no zombie remains after it exits."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        # Intermediate child.
        os.close(r)
        os.setsid()
        pid2 = os.fork()
        if pid2 == 0:
            # Grandchild: actual process.
            os.close(w)
            lf = open(logfile, "w")
            os.dup2(lf.fileno(), 1)
            os.dup2(lf.fileno(), 2)
            if cwd:
                os.chdir(cwd)
            # Close pipe fds and exec.
            try:
                os.execvp(cmd[0], cmd)
            except Exception:
                os._exit(127)
        else:
            os.write(w, str(pid2).encode())
            os.close(w)
            os._exit(0)
    # Parent: read grandchild PID, reap intermediate.
    os.close(w)
    data = b""
    while True:
        try:
            chunk = os.read(r, 32)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    os.close(r)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    return int(data.decode().strip())


def _monitor_path(name: str) -> Path:
    """Return the repo path for a monitor script."""
    return REPO_DIR / "tools" / "tokenharbor" / "monitors" / f"{name}_inject_monitor.py"


def _arm_inject_monitor(monitor_path: str, pid: int, ts: str, label: str,
                        count: int = 0, before_keys: list = None):
    """Spawn inject+notify monitor for a background farm PID."""
    import json as _json
    monitor = Path(monitor_path)
    if not monitor.exists():
        console.print(f"[yellow]⚠ Monitor script not found: {monitor_path}[/yellow]")
        return
    mlog = f"/tmp/{label}-inject-{ts}.log"
    args = [sys.executable, str(monitor), str(pid), str(count),
            _json.dumps(before_keys or [])]
    _spawn_detached(args, mlog)
    console.print(f"[dim]  {label} monitor armed[/dim]")


def _get_running_farms() -> list:
    """Return list of (name, pid, logfile) for running farm processes."""
    running = []
    # TokenHarbor: check pidfile + scan.
    pidfile = Path("/tmp/farm.pid")
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            logs = sorted(Path("/tmp").glob("farm-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            running.append(("TokenHarbor", pid, str(logs[0]) if logs else "-"))
        except (ValueError, OSError):
            pass
    # Mistral + Dahl + GonkaRouter: scan /proc.
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_text().replace("\x00", " ")
            if "dahl_farm.py" in cmd and "inject_monitor" not in cmd:
                logs = sorted(Path("/tmp").glob("dahl-farm-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                running.append(("Dahl", int(proc.name), str(logs[0]) if logs else "-"))
            elif "mistral_farm.py" in cmd and "inject_monitor" not in cmd:
                logs = sorted(Path("/tmp").glob("mistral-farm-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                running.append(("Mistral", int(proc.name), str(logs[0]) if logs else "-"))
            elif "gonka_farm" in cmd and "inject_monitor" not in cmd:
                logs = sorted(Path("/tmp").glob("gonka-farm-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                running.append(("GonkaRouter", int(proc.name), str(logs[0]) if logs else "-"))
        except OSError:
            pass
    return running


def menu_parallel_status():
    _clear_screen(); _header()
    console.print("\n[bold]  Parallel Farm — Status[/bold]\n")
    running = _get_running_farms()
    if not running:
        console.print("[dim]No farms running.[/dim]\n")
    else:
        t = Table(show_header=True, box=None, padding=(0, 2))
        t.add_column("Farm", style="white")
        t.add_column("PID", style="dim")
        t.add_column("Log", style="dim")
        for name, pid, log in running:
            t.add_row(name, str(pid), log)
        console.print(t)
        console.print()
        console.print("[dim]Pilih nomor untuk lihat log, [0] kembali[/dim]\n")
        for i, (name, pid, log) in enumerate(running, 1):
            console.print(f"[{i}] Lihat log {name}")
        console.print("[0] Back\n")
        c = Prompt.ask("Select", choices=[str(i) for i in range(len(running) + 1)],
                       default="0", show_choices=False)
        if c != "0":
            name, pid, log = running[int(c) - 1]
            if log != "-" and Path(log).exists():
                console.print(f"\n[dim]--- {log} (20 baris terakhir) ---[/dim]")
                lines = Path(log).read_text().splitlines()[-20:]
                for line in lines:
                    console.print(f"[dim]{line}[/dim]")
            else:
                console.print("[yellow]Log tidak ditemukan.[/yellow]")
            Prompt.ask("\nPress Enter to continue", default="")
            return
    Prompt.ask("Press Enter to continue", default="")


def menu_parallel_farm():
    _clear_screen(); _header()
    console.print("\n[bold]  Parallel Farm[/bold]\n")

    # Submenu: start new or check status.
    console.print("[1] Start new parallel farm")
    console.print("[2] Check running farms")
    console.print("[0] Back\n")
    c = Prompt.ask("Select", choices=["0", "1", "2"], default="1",
                   show_choices=False)
    if c == "2":
        menu_parallel_status()
        return
    if c == "0":
        return

    console.print("[dim]Run multiple farms simultaneously in background.[/dim]\n")

    proxies = _get_proxies()
    if not proxies:
        console.print("[yellow]⚠ No proxy configured.[/yellow]")
        console.print("Set proxies via main menu [magenta]Setup Proxy[/magenta].")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    # Step 1: select which farms to run (arrow keys + space).
    chosen = _curses_multiselect(
        "Select APIs to farm (↑↓ navigate, SPACE toggle, ENTER done, q cancel)",
        ["TokenHarbor", "Mistral", "Dahl", "GonkaRouter"],
    )
    if chosen is None:
        return  # cancelled with q
    if not chosen:
        console.print("\n[yellow]No farm selected.[/yellow]")
        Prompt.ask("\nPress Enter to continue", default="")
        return
    selected = [(str(i + 1), name) for i, name in enumerate(
        ["TokenHarbor", "Mistral", "Dahl", "GonkaRouter"]) if name in chosen]

    # Validate prerequisites per selected farm.
    state = _load_state()
    delay = state.get("delay", DEFAULT_DELAY)
    problems = []
    if any(name == "TokenHarbor" for _, name in selected):
        # TokenHarbor can run without Tempik/Capsolver (uses tempmail + browser auto-verify).
        # Show warnings but do not block.
        venv_python = REPO_DIR / ".venv" / "bin" / "python"
        email_prov = state.get("tokenharbor_email_provider", "tempmail")
        if email_prov == "tempik" and not _get_tempik_url():
            console.print("[yellow]⚠ Tempik URL not set — farm may fail at email step.[/yellow]")
        if not _get_capsolver():
            console.print("[yellow]⚠ Capsolver key not set — relying on browser auto-verify.[/yellow]")
    if any(name == "Mistral" for _, name in selected):
        _ms = _resolve_script(MISTRAL_SCRIPT, "tools/tokenharbor/mistral_farm.py")
        if not _ms.exists():
            problems.append(f"Mistral script not found: {MISTRAL_SCRIPT}")
    if any(name == "Dahl" for _, name in selected):
        _ds = _resolve_script(DAHL_SCRIPT, "tools/tokenharbor/dahl_farm.py")
        if not _ds.exists():
            problems.append(f"Dahl script not found: {DAHL_SCRIPT}")
    if any(name == "GonkaRouter" for _, name in selected):
        _gs = _resolve_script(GONKA_SCRIPT, "tools/tokenharbor/gonka_farm_email.py")
        if not _gs.exists():
            problems.append(f"GonkaRouter script not found: {GONKA_SCRIPT}")
    if problems:
        for p in problems:
            console.print(f"[red]✗ {p}[/red]")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    # Step 2: same batch count for all, or per farm?
    console.print()
    console.print("[1] Same batch count for all farms")
    console.print("[2] Different count per farm")
    mode = Prompt.ask("Batch mode", choices=["1", "2"], default="1",
                      show_choices=False)
    counts = {}
    if mode == "1":
        same = IntPrompt.ask("\nBatch count for all farms?", default=5)
        for _, name in selected:
            counts[name] = same
    else:
        for _, name in selected:
            counts[name] = IntPrompt.ask(f"{name} count?", default=5)

    console.print()
    for _, name in selected:
        console.print(f"[dim]{name}: {counts[name]}[/dim]")
    console.print()
    if not Confirm.ask(f"Start {len(selected)} farm(s) in background?", default=True):
        return

    # Snapshot existing keys BEFORE the runs (for per-run notifications).
    _p_before = {}
    if "TokenHarbor" in counts:
        _p_before["TokenHarbor"] = sorted(
            a.get("api_key") for a in _get_accounts() if a.get("api_key"))
    if "Mistral" in counts:
        _p_before["Mistral"] = sorted(
            k.get("api_key") for k in _get_mistral_keys() if k.get("api_key"))
    if "Dahl" in counts:
        _p_before["Dahl"] = sorted(
            k.get("api_key") for k in _get_dahl_keys() if k.get("api_key"))
    if "GonkaRouter" in counts:
        _p_before["GonkaRouter"] = sorted(
            k.get("api_key") for k in _get_gonka_keys() if k.get("api_key"))

    import datetime as _dt
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    procs = {}

    # TokenHarbor farm
    if "TokenHarbor" in counts:
        py = str(venv_python) if venv_python.exists() else sys.executable
        th_cmd = [py, "-m", "tools.tokenharbor.cli", "browser-farm",
                  "--count", str(counts["TokenHarbor"]), "--delay", str(delay),
                  "--email-provider", state.get("tokenharbor_email_provider", "tempmail")]
        th_log = f"/tmp/farm-{ts}.log"
        th_pid = _spawn_detached(th_cmd, th_log, cwd=str(REPO_DIR))
        procs["TokenHarbor"] = (th_pid, th_log)

    # Mistral farm
    if "Mistral" in counts:
        _ms = _resolve_script(MISTRAL_SCRIPT, "tools/tokenharbor/mistral_farm.py")
        mistral_cmd = [sys.executable, str(_ms),
                       "--count", str(counts["Mistral"])]
        mistral_log = f"/tmp/mistral-farm-{ts}.log"
        mistral_pid = _spawn_detached(mistral_cmd, mistral_log)
        procs["Mistral"] = (mistral_pid, mistral_log)

    # Dahl farm
    if "Dahl" in counts:
        _ds = _resolve_script(DAHL_SCRIPT, "tools/tokenharbor/dahl_farm.py")
        dahl_cmd = [sys.executable, str(_ds),
                    "--count", str(counts["Dahl"])]
        dahl_log = f"/tmp/dahl-farm-{ts}.log"
        dahl_pid = _spawn_detached(dahl_cmd, dahl_log)
        procs["Dahl"] = (dahl_pid, dahl_log)

    # GonkaRouter farm
    if "GonkaRouter" in counts:
        _gs = _resolve_script(GONKA_SCRIPT, "tools/tokenharbor/gonka_farm_email.py")
        gonka_cmd = [sys.executable, str(_gs),
                     "--count", str(counts["GonkaRouter"]),
                     "--out", str(GONKA_KEYS)]
        gonka_log = f"/tmp/gonka-farm-{ts}.log"
        gonka_pid = _spawn_detached(gonka_cmd, gonka_log)
        procs["GonkaRouter"] = (gonka_pid, gonka_log)

    console.print()
    for name, (pid, log) in procs.items():
        console.print(f"[green]✓ {name} farm started (PID {pid})[/green]")
        console.print(f"[dim]  Log: {log}[/dim]")

    # Arm monitors if auto-inject ON or Telegram configured.
    state = _load_state()
    _monitors = {
        "TokenHarbor": ("tokenharbor_auto_inject", str(_monitor_path("tokenharbor")), "tokenharbor"),
        "Mistral": ("mistral_auto_inject", str(_monitor_path("mistral")), "mistral"),
        "Dahl": ("dahl_auto_inject", str(_monitor_path("dahl")), "dahl"),
        "GonkaRouter": ("gonka_auto_inject", str(_monitor_path("gonka")), "gonka"),
    }
    for name, (pid, _) in procs.items():
        inject_key, mon_path, label = _monitors[name]
        if _should_arm_monitor(state, inject_key) or state.get(inject_key + "_omniroute", False):
            _arm_inject_monitor(mon_path, pid, ts, label,
                                counts.get(name, 0), _p_before.get(name, []))

    console.print("\n[dim]All keep running after disconnect.[/dim]")
    Prompt.ask("\nPress Enter to continue", default="")


# Telegram Premium custom emoji IDs (from emojiPremium.js).
# Rendered via <tg-emoji emoji-id="..."> in HTML parse mode.
PREMIUM_EMOJI = {
    "✅": "6240299739754013144",
    "📦": "6237742692319634626",
    "🟢": "6237911132347048956",
    "🔴": "6237493953583654024",
    "🔑": "6240083509625495534",
    "🔄": "6240294882145999585",
    "⚠️": "6239942578863613477",
    "❌": "6237771971111691142",
    "🎉": "6237921788160910249",
    "⏳": "6237942489903276139",
}

# Named custom emojis (from emojiPremium.js codebase).
NAMED_EMOJI = {
    "phone_order": "5967591100532134862",  # ☎️
    "phone_apps": "5407025283456835913",   # 📱
}


def tg_emoji(emoji_id: str, fallback: str = "⭐") -> str:
    """Build a <tg-emoji> tag from a custom emoji ID directly."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def named_emoji(name: str, fallback: str = "⭐") -> str:
    """Get a named custom emoji tag (phone_order, phone_apps)."""
    eid = NAMED_EMOJI.get(name)
    if not eid:
        return fallback
    return tg_emoji(eid, fallback)


def get_first_emoji(text: str):
    """Extract the first emoji from button text (for icon_custom_emoji_id)."""
    import re
    m = re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]", text)
    return m.group(0) if m else None


def build_button(text: str, callback_data=None, extra=None) -> dict:
    """Build a Telegram button dict with Bot API 9.4 support.

    extra may contain: url, style ("primary"|"success"|"danger"),
    icon_custom_emoji_id (auto-detected from first emoji in text).
    """
    extra = extra or {}
    btn = {"text": text}
    if callback_data:
        btn["callback_data"] = callback_data
    if extra.get("url"):
        btn["url"] = extra["url"]
    if extra.get("style"):
        btn["style"] = extra["style"]
    if extra.get("icon_custom_emoji_id"):
        btn["icon_custom_emoji_id"] = extra["icon_custom_emoji_id"]
    else:
        first = get_first_emoji(text)
        if first and first in PREMIUM_EMOJI:
            btn["icon_custom_emoji_id"] = PREMIUM_EMOJI[first]
    return btn


def _premium_emoji(text: str) -> str:
    """Wrap known emojis in <tg-emoji> tags. Idempotent."""
    import re
    # Skip already-wrapped segments.
    saved = []

    def _save(m):
        saved.append(m.group(0))
        return f"\x00PREMIUM{len(saved) - 1}\x00"

    safe = re.sub(r"<tg-emoji[^>]*>.*?</tg-emoji>", _save, text, flags=re.DOTALL)
    for emoji, eid in PREMIUM_EMOJI.items():
        safe = safe.replace(emoji, f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>')
    for i, orig in enumerate(saved):
        safe = safe.replace(f"\x00PREMIUM{i}\x00", orig)
    return safe


def _send_telegram(text: str) -> tuple:
    """Send Telegram notification. Returns (ok: bool, msg: str)."""
    import urllib.request
    state = _load_state()
    token = state.get("telegram_bot_token")
    chat_id = state.get("telegram_chat_id")
    if not token or not chat_id:
        return False, "Telegram not configured."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": _premium_emoji(text),
        "parse_mode": "HTML",
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                return True, "Sent."
            return False, result.get("description", "Unknown error")
    except Exception as e:
        return False, str(e)


_INJECT_STATE_KEYS = {
    "TokenHarbor": "tokenharbor_auto_inject",
    "Mistral": "mistral_auto_inject",
    "Dahl": "dahl_auto_inject",
    "Nscale": "nscale_auto_inject",
}


def _proxy_summary() -> str:
    """Return a safe proxy summary for notifications (no credentials)."""
    try:
        proxies = _get_proxies()
    except Exception:
        return "no proxy"
    if not proxies:
        return "no proxy"
    # Mask credentials, show only host.
    hosts = []
    for p in proxies[:3]:
        # Format: user:pass@host:port or host:port
        host = p.split("@")[-1] if "@" in p else p
        # Remove user:pass prefix if present without @
        if host.count(":") > 1:
            host = ":".join(host.split(":")[-2:])
        hosts.append(host)
    more = f" +{len(proxies)-3}" if len(proxies) > 3 else ""
    return f"{len(proxies)} proxy ({', '.join(hosts)}{more})"


def _notify_farm_done(provider: str, total: int, success: int, failed: int,
                      keys: list = None, progress: str = None,
                      emails: list = None):
    """Send farm completion notification to Telegram if configured.
    If progress is set (e.g. "150/1000"), title shows progress instead."""
    import html as _html
    state = _load_state()
    if not state.get("telegram_bot_token") or not state.get("telegram_chat_id"):
        return
    inject_on = state.get(_INJECT_STATE_KEYS.get(provider, ""), False)
    inject_txt = "ON✓" if inject_on else "OFF<b>✗</b>"
    inject_om = state.get(_INJECT_STATE_KEYS.get(provider, "") + "_omniroute", False)
    inject_om_txt = "ON✓" if inject_om else "OFF<b>✗</b>"

    # Base URLs for the notification.
    _base_urls = {
        "TokenHarbor": "https://tokenharbor.ai/v1",
        "GonkaRouter": "https://api.gonkarouter.io/v1",
        "Nscale": "https://inference.api.nscale.com/v1",
    }
    base_url = _base_urls.get(provider, "")

    title = f"✓Farm Selesai — {provider}" if not progress else f"Farm Progress — {provider} ({progress})"
    text = (
        f"{title}\n"
        f"\n"
        f"{len(keys or [])} API Key:\n"
        f"Total:{total} | ✓Success:{success} | <b>✗</b>Failed:{failed}\n"
    )
    if keys:
        # Code block -> Telegram shows COPY CODE button.
        escaped = "\n".join(_html.escape(k) for k in keys)
        text += f"<pre>{escaped}</pre>\n"
    if emails:
        # Second code block: Tempik emails, same order as the keys above.
        escaped_emails = "\n".join(_html.escape(e) for e in emails)
        text += f"<pre>{escaped_emails}</pre>\n"
    if base_url:
        text += f"\nBase URL: <code>{_html.escape(base_url)}</code>"
    text += f"\nAuto inject 9Router: <b>{inject_txt}</b>"
    text += f"\nAuto inject OmniRoute: <b>{inject_om_txt}</b>"
    text += f"\nProxy: {_proxy_summary()}"
    ok, msg = _send_telegram(text)
    return ok


# Chunk size for progress notifications on large batches.
NOTIFY_CHUNK = 30


def menu_setup_telegram():
    _clear_screen(); _header()
    console.print("\n[bold bright_cyan]  Setup Bot Telegram[/bold bright_cyan]\n")
    state = _load_state()
    cur_token = state.get("telegram_bot_token", "")
    cur_chat = state.get("telegram_chat_id", "")
    if cur_token:
        console.print(f"  [dim]Bot token:[/dim] [green]set ({cur_token[:10]}...)")
        console.print(f"  [dim]Chat ID:[/dim] [green]{cur_chat}[/green]\n")
    else:
        console.print("  [dim]Belum dikonfigurasi.[/dim]\n")

    console.print("[1] Set / update Bot Token & Chat ID")
    console.print("[2] Test kirim pesan")
    console.print("[3] Hapus konfigurasi")
    console.print("[0] Back\n")
    choice = Prompt.ask("Select", choices=["0", "1", "2", "3"], default="0",
                        show_choices=False)
    if choice == "1":
        token = Prompt.ask("Bot Token", default=cur_token or "")
        chat_id = Prompt.ask("Chat ID", default=cur_chat or "")
        if token and chat_id:
            state["telegram_bot_token"] = token.strip()
            state["telegram_chat_id"] = chat_id.strip()
            _save_state(state)
            console.print("\n[green]✓ Telegram dikonfigurasi.[/green]")
        else:
            console.print("\n[yellow]Dibatalkan — token dan chat ID wajib diisi.[/yellow]")
    elif choice == "2":
        if not cur_token or not cur_chat:
            console.print("\n[yellow]Belum dikonfigurasi. Set dulu via [1].[/yellow]")
        else:
            ok, msg = _send_telegram("<b>Test notifikasi</b>\nBot Telegram terhubung! ✓")
            if ok:
                console.print("\n[green]✓ Pesan test terkirim![/green]")
            else:
                console.print(f"\n[red]✗ Gagal: {msg}[/red]")
    elif choice == "3":
        state.pop("telegram_bot_token", None)
        state.pop("telegram_chat_id", None)
        _save_state(state)
        console.print("\n[dim]Konfigurasi Telegram dihapus.[/dim]")
    Prompt.ask("\nPress Enter to continue", default="")


def menu_uninstall():
    """Uninstall universal-farm: remove code, farm command, results, and state."""
    import shutil
    _clear_screen(); _header()
    console.print("\n[bold red]  Uninstall Universal Farm[/bold red]\n")
    console.print("This will [bold]DELETE[/bold]:")
    console.print(f"  - {REPO_DIR} (all farm code)")
    console.print("  - farm command (/usr/local/bin/farm or ~/.local/bin/farm)")
    console.print("  - All farmed keys, progress files, and Telegram/bot state\n")
    console.print("[dim]9Router is NOT touched.[/dim]\n")

    confirm = Prompt.ask("Type [bold red]DELETE[/bold red] to confirm",
                         default="", show_default=False)
    if confirm != "DELETE":
        console.print("\n[yellow]Cancelled.[/yellow]")
        Prompt.ask("\nPress Enter to continue", default="")
        return

    console.print()
    # 1. Kill running farms.
    console.print("[dim]Stopping running farms...[/dim]")
    import subprocess as _sp
    for pat in ["dahl_farm.py", "gonka_farm.py", "gonka_farm_email.py", "mistral_farm.py",
                "tools.tokenharbor.cli", "inject_monitor.py"]:
        _sp.run(["pkill", "-f", pat], capture_output=True)
    # 2. Remove farm command.
    for bin in [Path("/usr/local/bin/farm"), Path.home() / ".local/bin/farm"]:
        try:
            if bin.exists() or bin.is_symlink():
                bin.unlink()
                console.print(f"[dim]removed {bin}[/dim]")
        except OSError as e:
            console.print(f"[yellow]could not remove {bin}: {e}[/yellow]")
    # 3. Remove results, progress, state.
    for f in [Path.home() / "dahl_keys.txt",
              Path.home() / "mistral_keys.txt",
              Path.home() / "gonka_keys.txt",
              Path.home() / "dahl_keys_export.txt",
              Path.home() / "mistral_keys_export.txt",
              Path.home() / "gonka_keys_export.txt",
              Path.home() / "dahl_farm_progress.txt",
              Path.home() / "mistral_farm_progress.txt",
              Path.home() / "gonka_farm_progress.txt",
              Path.home() / ".farm_tui.json"]:
        try:
            if f.exists():
                f.unlink()
                console.print(f"[dim]removed {f}[/dim]")
        except OSError:
            pass
    for pat in ["farm-*.log", "dahl-farm-*.log", "mistral-farm-*.log",
                "gonka-farm-*.log", "signup-fail-*.png"]:
        for log in Path("/tmp").glob(pat):
            try:
                log.unlink()
            except OSError:
                pass
    try:
        Path("/tmp/farm.pid").unlink(missing_ok=True)
    except OSError:
        pass
    # 4. Remove repo dir last (we are running from it).
    console.print(f"[dim]removing {REPO_DIR}...[/dim]")
    console.print("\n[green]✓ Uninstall complete. Bye.[/green]")
    try:
        shutil.rmtree(REPO_DIR, ignore_errors=True)
    except Exception:
        pass
    raise SystemExit(0)


def main():
    while True:
        _clear_screen()
        _header()
        state = _load_state()
        proxies = _get_proxies()
        tempik = _get_tempik_url()
        capsolver = _get_capsolver()

        _status_line(state, proxies, tempik, capsolver)
        console.print()

        menu = Table(show_header=False, box=None, padding=(0, 2))
        menu.add_column("key", width=5, justify="right")
        menu.add_column("label", style="white")
        menu.add_column("hint", style="dim")
        # Gradient numbers: sample FARM_GRADIENT across the menu items.
        _nums = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "0"]
        def _gnum(n):
            idx = _nums.index(n)
            t = idx / max(len(_nums) - 1, 1)
            for s in range(len(FARM_GRADIENT) - 1):
                p0, c0 = FARM_GRADIENT[s]
                p1, c1 = FARM_GRADIENT[s + 1]
                if p0 <= t <= p1:
                    f = (t - p0) / max(p1 - p0, 1e-9)
                    r = int(c0[0] + (c1[0] - c0[0]) * f)
                    g = int(c0[1] + (c1[1] - c0[1]) * f)
                    b = int(c0[2] + (c1[2] - c0[2]) * f)
                    break
            else:
                r, g, b = FARM_GRADIENT[-1][1]
            return Text(f"[{n}]", style=f"bold #{r:02x}{g:02x}{b:02x}")
        menu.add_row(_gnum("1"), "Farm TokenHarbor", "TokenHarbor account farming")
        menu.add_row(_gnum("2"), "Farm Mistral keys", "Mistral API key farming")
        menu.add_row(_gnum("3"), "Farm Dahl keys", "Dahl Inference API keys")
        menu.add_row(_gnum("4"), "Farm GonkaRouter keys", "GonkaRouter API keys (email + OTP)")
        menu.add_row(_gnum("5"), "Farm Nscale keys", "Nscale API keys (real Chrome)")
        menu.add_row(_gnum("6"), "Parallel farm", "run farms in background")
        menu.add_row(_gnum("7"), "Delay setting", f"currently {state['delay']}s")
        menu.add_row(_gnum("8"), "Setup Proxy", f"{len(proxies)} configured" if proxies else "not configured")
        menu.add_row(_gnum("9"), "Setup Bot Tele", "Telegram notifications")
        menu.add_row(_gnum("10"), "Uninstall", "remove farm completely")
        menu.add_row(_gnum("11"), "Setup capsolver", "shared by all farms")
        menu.add_row(_gnum("12"), "Setup GSuite accounts", "Nscale: bulk / single email + password")
        menu.add_row(_gnum("0"), "Exit", "")
        console.print(menu, justify="center")
        console.print()
        choice = Prompt.ask("    [dim]Select Action[/dim]", choices=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
                            default="1", show_choices=False, show_default=False)
        if choice == "1":
            menu_tokenharbor()
        elif choice == "2":
            menu_mistral()
        elif choice == "3":
            menu_dahl()
        elif choice == "4":
            menu_gonka()
        elif choice == "5":
            menu_nscale()
        elif choice == "6":
            menu_parallel_farm()
        elif choice == "7":
            menu_delay_setting()
        elif choice == "8":
            menu_setup_proxy()
        elif choice == "9":
            menu_setup_telegram()
        elif choice == "10":
            menu_uninstall()
        elif choice == "11":
            menu_setup_capsolver()
        elif choice == "12":
            menu_setup_gsuite()
        else:
            console.print("\nBye.")
            break


if __name__ == "__main__":
    main()
