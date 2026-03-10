"""Quick test: login via Google, then test the /applystart redirect on one job."""
import sys, os, time, signal
sys.path.insert(0, "src")
sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)
from camoufox.sync_api import Camoufox

def alarm_handler(signum, frame):
    print("ALARM - force exit"); os._exit(0)
signal.signal(signal.SIGALRM, alarm_handler)
signal.alarm(120)

cm = Camoufox(headless=False, humanize=True)
browser = cm.__enter__()
ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
page = ctx.new_page()

# Login
print("Opening sign-in page...")
page.goto("https://secure.indeed.com/auth", timeout=20000, wait_until="commit")
time.sleep(3)
print(f"Auth page: {page.title()}")
print("\nComplete Google sign-in in the browser, then press ENTER here...")
input(">>> ")

# Verify login
page.goto("https://www.indeed.com", timeout=20000, wait_until="commit")
time.sleep(3)
print(f"Indeed homepage: {page.title()}")

# Load job page
jk = "162a100fceae998c"
page.goto(f"https://www.indeed.com/viewjob?jk={jk}", timeout=20000, wait_until="commit")
time.sleep(4)
print(f"Job page: {page.title()}")

# Get apply href
btn = page.locator('button[href*="applystart"]').first
if btn.count() == 0:
    print("No applystart button found!")
    # Try other buttons
    all_btns = page.locator("button").all()
    for b in all_btns:
        try:
            t = b.inner_text().strip()
            if "apply" in t.lower():
                h = b.get_attribute("href") or "none"
                print(f"  Button: '{t}' href={h[:80]}")
        except:
            pass
    os._exit(1)

href = btn.get_attribute("href")
print(f"Apply href: {href[:100]}")

# Open in a new tab
print("\nOpening apply URL in new tab...")
new_page = ctx.new_page()
try:
    new_page.goto(href, timeout=45000, wait_until="domcontentloaded")
except Exception as e:
    print(f"Timeout (checking URL anyway): {str(e)[:80]}")

time.sleep(3)
final_url = new_page.url
title = new_page.title()
print(f"New tab URL: {final_url}")
print(f"New tab title: {title}")

if "indeed.com" not in final_url:
    print("SUCCESS - redirected to external ATS!")
    body = new_page.locator("body").inner_text()[:300]
    print(f"Body: {body}")
elif "smartapply" in final_url:
    print("SmartApply flow detected")
elif "just a moment" in title.lower():
    print("Cloudflare challenge - waiting...")
    for i in range(12):
        time.sleep(5)
        if "just a moment" not in new_page.title().lower():
            print(f"Cloudflare cleared! URL: {new_page.url}")
            break
        print(f"  Still waiting... [{(i+1)*5}s]")
else:
    body = new_page.locator("body").inner_text()[:500]
    print(f"Body: {body}")

new_page.close()
page.close()
ctx.close()
os._exit(0)
