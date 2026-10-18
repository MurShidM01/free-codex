"""One-time interactive Puter Web authentication command."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from typing import Any

from .providers.base import ProviderUnavailableError
from .services.puter_browser import PuterBrowserManager
from .utils.config import ProviderDefinition, ProviderType, Settings, settings


_AUTH_PAGE = """<!doctype html><html><head><meta charset='utf-8'>
<title>Free Codex — Puter sign in</title><script src='https://js.puter.com/v2/'></script>
<style>body{font:16px system-ui;margin:3rem;max-width:42rem;color:#172033}code{background:#eef;padding:.2rem}</style>
</head><body><h1>Free Codex Puter sign in</h1><p>Complete Puter sign-in in the official dialog/window if prompted.</p>
<p>This page uses the public Puter.js SDK only. Free Codex does not read or display your credentials, cookies, or tokens.</p>
<p id='state'>Loading Puter.js…</p><script>
(async()=>{const out=document.getElementById('state');try {if(!window.puter||!puter.auth) throw new Error('Puter.js unavailable');
let ok=false;if(typeof puter.auth.isSignedIn==='function') ok=!!(await puter.auth.isSignedIn());
if(!ok && typeof puter.auth.signIn==='function') {out.textContent='Waiting for sign-in…'; await puter.auth.signIn();}
if(typeof puter.auth.isSignedIn==='function') ok=!!(await puter.auth.isSignedIn());
out.textContent=ok?'Signed in. You can close this window.':'Sign-in is still required.';
} catch(e){out.textContent='Authentication could not start. Check your network and retry.';}})();
</script></body></html>"""


async def _run_auth(definition: ProviderDefinition, timeout: int) -> bool:
    manager = PuterBrowserManager(definition)
    context: Any = None
    try:
        context = await manager._launch_context(headless=False)
        pages = getattr(context, "pages", []) or []
        page = pages[0] if pages else await context.new_page()
        await page.set_content(_AUTH_PAGE, wait_until="domcontentloaded")
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            try:
                authenticated = await page.evaluate("""async () => {
                  try {
                    if (!window.puter || !puter.auth) return false;
                    if (typeof puter.auth.isSignedIn === 'function') return !!(await puter.auth.isSignedIn());
                    if (typeof puter.auth.getUser === 'function') return !!(await puter.auth.getUser());
                    return false;
                  } catch (_) { return false; }
                }""")
                if authenticated:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if manager._playwright is not None:
            try:
                await manager._playwright.stop()
            except Exception:
                pass


def run_puter_auth() -> None:
    parser = argparse.ArgumentParser(prog="fc-puter-auth", description="Authenticate a persistent Puter.js browser profile once.")
    parser.add_argument("--timeout", type=int, default=None, help="Seconds to wait for user sign-in.")
    parser.add_argument("--browser", help="chromium, chrome, edge, or a Chromium executable path.")
    parser.add_argument("--profile-dir", help="Persistent browser profile directory.")
    args = parser.parse_args()

    config = settings
    config.reload()
    definition = config.provider_definitions.get("puter_web")
    if definition is None:
        definition = ProviderDefinition(id="puter_web", type=ProviderType.PUTER_WEB, enabled=True)
    options = dict(definition.options)
    if args.browser:
        options["browser"] = args.browser
    if args.profile_dir:
        options["profile_dir"] = args.profile_dir
    definition = replace(definition, enabled=True, options=options)
    timeout = max(10, args.timeout or int(options.get("auth_timeout") or 300))
    print("Opening a visible browser for one-time Puter authentication…", flush=True)
    try:
        authenticated = asyncio.run(_run_auth(definition, timeout))
    except ProviderUnavailableError as exc:
        print("Error: {0}".format(exc))
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("Authentication cancelled.")
        raise SystemExit(130)
    if not authenticated:
        print("Puter authentication was not confirmed before timeout. Run fc-puter-auth again.")
        raise SystemExit(3)
    print("Puter authentication confirmed. Future fc-server/fc-codex requests will use the hidden persistent browser profile.")
