"""Debug Glassdoor job card structure."""
import sys
import time
sys.path.insert(0, "src")

from pathlib import Path
from camoufox.sync_api import Camoufox

STATE_FILE = Path("~/.job-agent/browser_state/glassdoor_camoufox.json").expanduser()

with Camoufox(headless=False, humanize=True) as browser:
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        storage_state=str(STATE_FILE),
    )
    page = ctx.new_page()

    page.goto("https://www.glassdoor.com/Job/jobs.htm?sc.keyword=software+engineer", timeout=60000, wait_until="commit")
    time.sleep(8)

    for _ in range(6):
        if "just a moment" not in page.title().lower():
            break
        time.sleep(5)

    print(f"Title: {page.title()}")

    # Check what wait_for_selector does
    try:
        page.wait_for_selector('[data-test="jobListing"]', timeout=10000)
        print("wait_for_selector: OK")
    except Exception as e:
        print(f"wait_for_selector FAILED: {e}")

    cards = page.locator('[data-test="jobListing"]').all()
    print(f"\nFound {len(cards)} job cards")

    for i, card in enumerate(cards[:3]):
        print(f"\n--- Card {i+1} ---")
        # Check old selectors
        for sel_name, sel in [
            ("job-title", '[data-test="job-title"]'),
            ("job-title2", ".job-title"),
            ("emp-name", '[data-test="emp-name"]'),
            ("employer-name", ".employer-name"),
            ("emp-location", '[data-test="emp-location"]'),
            ("location", ".location"),
            ("link", "a[href*='/job-listing/']"),
            ("salary", '[data-test="detailSalary"]'),
            ("salary2", ".salary-estimate"),
        ]:
            el = card.locator(sel).first
            if el.count() > 0:
                try:
                    text = el.inner_text().strip()[:60]
                    print(f"  {sel_name}: '{text}'")
                except Exception:
                    print(f"  {sel_name}: (exists but no text)")
            else:
                pass  # Don't print missing ones to reduce noise

        # Dump the card's inner HTML structure
        html = card.evaluate("el => el.innerHTML.substring(0, 500)")
        print(f"  HTML: {html[:300]}")

    page.close()
    ctx.close()
