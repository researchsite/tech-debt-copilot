"""
Take screenshots of the Tech Debt Copilot Streamlit app.
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8501"

def scroll_to(page, px=0):
    page.evaluate(f"""() => {{
        // Try every candidate scroll container Streamlit might use
        const candidates = [
            'section[data-testid="stMain"]',
            '[data-testid="stMain"]',
            '.main',
            '[data-testid="stAppViewContainer"]',
        ];
        for (const sel of candidates) {{
            const el = document.querySelector(sel);
            if (el && el.scrollHeight > el.clientHeight) {{
                el.scrollTop = {px};
            }}
        }}
        document.documentElement.scrollTop = {px};
        document.body.scrollTop = {px};
        window.scrollTo(0, {px});
    }}""")
    time.sleep(1.0)

def scroll_bottom(page):
    page.evaluate("""() => {
        const candidates = [
            'section[data-testid="stMain"]',
            '[data-testid="stMain"]',
            '.main',
            '[data-testid="stAppViewContainer"]',
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el && el.scrollHeight > el.clientHeight) {
                el.scrollTop = el.scrollHeight;
            }
        }
        window.scrollTo(0, document.body.scrollHeight);
    }""")
    time.sleep(1.0)

def wait_done(page, timeout=50):
    """Poll until st.status shows Done and no spinner."""
    start = time.time()
    while time.time() - start < timeout:
        done    = page.locator("[data-testid='stStatusWidget']").filter(has_text="Done")
        spinner = page.locator("[data-testid='stSpinner']")
        asst    = page.locator("[data-testid='chatAvatarIcon-assistant']")
        if (done.count() > 0 or asst.count() > 0) and spinner.count() == 0:
            time.sleep(2.5)
            return
        time.sleep(1.2)
    time.sleep(4)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # ── 1. Home page ─────────────────────────────────────────────
    page.goto(URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)
    scroll_to(page, 0)
    page.screenshot(path=str(OUT / "01_home.png"), full_page=False)
    print("OK 01_home.png")

    # ── 2. Local stack scan ───────────────────────────────────────
    page.locator("button").filter(has_text="Scan").first.click()
    print("   local scan in progress ...")
    wait_done(page, timeout=50)

    # Scroll the kicker element into view (top of page)
    kicker = page.locator(".kicker").first
    if kicker.count():
        kicker.scroll_into_view_if_needed()
        time.sleep(1)
    page.screenshot(path=str(OUT / "02_metrics_top.png"), full_page=False)
    print("OK 02_metrics_top.png")

    # Scroll to metrics grid specifically
    metrics = page.locator(".metrics-grid").first
    if metrics.count():
        metrics.scroll_into_view_if_needed()
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "03_metrics_cards.png"), full_page=False)
        print("OK 03_metrics_cards.png")
    else:
        print("   (no .metrics-grid found — dashboard may not have rendered)")

    # Scroll to stack expander rows
    exp = page.locator("[data-testid='stExpander']").first
    if exp.count():
        exp.scroll_into_view_if_needed()
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "04_stack_rows.png"), full_page=False)
        print("OK 04_stack_rows.png")

    # Chat response
    asst = page.locator("[data-testid='chatAvatarIcon-assistant']").first
    if asst.count():
        asst.scroll_into_view_if_needed()
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "05_chat_response.png"), full_page=False)
        print("OK 05_chat_response.png")

    # ── 3. Django repo scan ───────────────────────────────────────
    page.locator("button").filter(has_text="New Conversation").first.click()
    time.sleep(2.5)

    page.locator("button").filter(has_text="Django Legacy").first.click()
    print("   Django repo scan in progress ...")
    wait_done(page, timeout=55)

    kicker2 = page.locator(".kicker").first
    if kicker2.count():
        kicker2.scroll_into_view_if_needed()
        time.sleep(1)
    page.screenshot(path=str(OUT / "06_repo_top.png"), full_page=False)
    print("OK 06_repo_top.png")

    metrics2 = page.locator(".metrics-grid").first
    if metrics2.count():
        metrics2.scroll_into_view_if_needed()
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "07_repo_metrics.png"), full_page=False)
        print("OK 07_repo_metrics.png")
    else:
        print("   (no .metrics-grid for repo scan)")

    asst2 = page.locator("[data-testid='chatAvatarIcon-assistant']").first
    if asst2.count():
        asst2.scroll_into_view_if_needed()
        time.sleep(0.8)
        page.screenshot(path=str(OUT / "08_repo_chat.png"), full_page=False)
        print("OK 08_repo_chat.png")

    browser.close()

print(f"\nDone. All screenshots in: {OUT.resolve()}")
