"""Debug Glassdoor page structure to find correct selectors."""
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

    # Wait through Cloudflare
    for _ in range(12):
        if "just a moment" not in page.title().lower():
            break
        time.sleep(5)

    print(f"Title: {page.title()}")
    print(f"URL: {page.url}")

    # Try various selectors to find job cards
    selectors = [
        '[data-test="jobListing"]',
        '.react-job-listing',
        '.JobCard_jobCardContainer__arDln',
        '[data-test="job-card"]',
        'li[data-test]',
        '.jobCard',
        '.job-listing',
        'a[href*="/job-listing/"]',
        'a[href*="/partner/jobListing"]',
        '[class*="JobCard"]',
        '[class*="jobCard"]',
        '[class*="job-card"]',
        '[class*="JobsList"]',
        '[class*="jobsList"]',
        'ul[class*="Jobs"] > li',
        'div[class*="JobsList"] > *',
        '[data-brandviews]',
        '[data-id]',
        '[data-job-id]',
        '[data-eh-id]',
    ]

    for sel in selectors:
        count = page.locator(sel).count()
        if count > 0:
            print(f"  FOUND {count:3d} elements: {sel}")

    # Dump first few elements with useful attributes
    print("\n--- All <a> tags with job-related hrefs ---")
    links = page.locator('a[href*="job"], a[href*="Job"]').all()
    for link in links[:15]:
        try:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()[:60]
            if text and ("job" in href.lower() or "listing" in href.lower()):
                print(f"  <a href='{href[:80]}'>{text}</a>")
        except Exception:
            pass

    # Dump main content area class names
    print("\n--- Main content area classes ---")
    main_els = page.locator("main, [role='main'], #MainCol, .main-content").all()
    for el in main_els[:3]:
        try:
            cls = el.get_attribute("class") or ""
            tag = el.evaluate("el => el.tagName")
            children = el.evaluate("el => el.children.length")
            c = cls[:80]
            print(f"  <{tag} class='{c}'> children={children}")
        except Exception:
            pass

    # Get a snapshot of the body HTML structure (first level)
    print("\n--- Body > children tags ---")
    body_children = page.evaluate("""
        () => {
            const body = document.body;
            return Array.from(body.children).slice(0, 10).map(el => {
                return `<${el.tagName} id="${el.id}" class="${el.className.toString().substring(0,60)}">`;
            });
        }
    """)
    for child in body_children:
        print(f"  {child}")

    # Look for any list items that could be job cards
    print("\n--- Lists with multiple items ---")
    lists = page.evaluate("""
        () => {
            const uls = document.querySelectorAll('ul, ol');
            const results = [];
            for (const ul of uls) {
                if (ul.children.length >= 3) {
                    const cls = ul.className.toString().substring(0, 80);
                    const firstChild = ul.children[0];
                    const fcCls = firstChild ? firstChild.className.toString().substring(0, 60) : '';
                    results.push(`<${ul.tagName} class="${cls}"> children=${ul.children.length} firstChild=<${firstChild?.tagName} class="${fcCls}">`);
                }
            }
            return results.slice(0, 10);
        }
    """)
    for item in lists:
        print(f"  {item}")

    page.close()
    ctx.close()
