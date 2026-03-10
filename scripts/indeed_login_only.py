"""Login to Indeed via Google auth and save session cookies.

Run this once, then the apply script can reuse the session.
"""
import sys
import time
sys.path.insert(0, "src")

from pathlib import Path
from camoufox.sync_api import Camoufox

STATE_FILE = Path("~/.job-agent/browser_state/indeed_camoufox.json").expanduser()
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

print("Opening browser for Indeed login...")
with Camoufox(headless=False, humanize=True) as browser:
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    page.goto("https://secure.indeed.com/auth", timeout=30000, wait_until="commit")
    time.sleep(3)

    print("\n" + "=" * 50)
    print("Click 'Continue with Google' and complete sign-in.")
    print("Press ENTER here when done...")
    print("=" * 50 + "\n")
    input(">>> ")

    # Save cookies
    ctx.storage_state(path=str(STATE_FILE))
    print(f"Session saved to {STATE_FILE}")

    # Quick verify
    page.goto("https://www.indeed.com/viewjob?jk=162a100fceae998c", timeout=20000, wait_until="commit")
    time.sleep(3)
    btn = page.locator('button[href*="applystart"]').first
    if btn.count() > 0:
        print("Login verified - apply buttons visible!")
    else:
        print(f"Warning: page title = {page.title()}")

    page.close()
    ctx.close()

print("Done. You can now let the agent run the apply script.")
