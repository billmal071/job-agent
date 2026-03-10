"""Debug Glassdoor company name selector."""
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

    card = page.locator('[data-test="jobListing"]').first

    # Dump all data-test attributes inside the card
    attrs = card.evaluate("""el => {
        const results = [];
        el.querySelectorAll('[data-test]').forEach(e => {
            results.push({
                tag: e.tagName,
                dataTest: e.getAttribute('data-test'),
                text: e.innerText.substring(0, 60),
                cls: e.className.toString().substring(0, 60)
            });
        });
        return results;
    }""")
    print("--- data-test attributes in card ---")
    for attr in attrs:
        print(f"  <{attr['tag']} data-test='{attr['dataTest']}' class='{attr['cls']}'> {attr['text']}")

    # Also check class-based selectors for company
    company_selectors = [
        '[class*="EmployerProfile"]',
        '[class*="employer"]',
        '[class*="Employer"]',
        '[class*="company"]',
        '[class*="Company"]',
    ]
    print("\n--- Company-related classes ---")
    for sel in company_selectors:
        els = card.locator(sel).all()
        for el in els[:3]:
            try:
                text = el.inner_text().strip()[:60]
                cls = el.get_attribute("class") or ""
                tag = el.evaluate("el => el.tagName")
                print(f"  <{tag} class='{cls[:60]}'> {text}")
            except Exception:
                pass

    page.close()
    ctx.close()
