"""Login to Glassdoor via Google auth and save session cookies.

Run this once, then the discovery/apply script can reuse the session.
"""

import sys
import time

sys.path.insert(0, "src")

from pathlib import Path
from camoufox.sync_api import Camoufox

STATE_FILE = Path("~/.job-agent/browser_state/glassdoor_camoufox.json").expanduser()
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

print("Opening browser for Glassdoor login...")
with Camoufox(headless=False, humanize=True) as browser:
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    page.goto(
        "https://www.glassdoor.com/profile/login_input.htm",
        timeout=30000,
        wait_until="commit",
    )
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
    page.goto(
        "https://www.glassdoor.com/Job/jobs.htm?sc.keyword=software+engineer",
        timeout=20000,
        wait_until="commit",
    )
    time.sleep(3)
    cards = page.locator(
        '[data-test="jobListing"], .react-job-listing, .JobCard_jobCardContainer__arDln'
    ).count()
    if cards > 0:
        print(f"Login verified - found {cards} job listings!")
    else:
        print(f"Warning: page title = {page.title()}")

    page.close()
    ctx.close()

print("Done. You can now run scripts/glassdoor_discover_and_apply.py")
