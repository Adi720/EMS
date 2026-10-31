"""Capture the documentation screenshots in docs/images from a running dev server.

Only for documentation; needs Playwright, which is NOT a project dependency:

    .venv\\Scripts\\python.exe -m pip install playwright
    .venv\\Scripts\\python.exe -m playwright install chromium

Use a database filled with made-up data only (never real contacts):

    set DATABASE_URL=sqlite:///docs-demo.sqlite3
    .venv\\Scripts\\python.exe manage.py migrate
    .venv\\Scripts\\python.exe manage.py seed_demo_data --password <password>
    .venv\\Scripts\\python.exe manage.py runserver 8000
    .venv\\Scripts\\python.exe scripts\\docs_screenshots.py http://127.0.0.1:8000 <password>
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

COORDINATOR_PAGES = [
    ("coordinator-dashboard.png", "/coordinator/", 2200),
    ("saints-directory.png", "/contacts/", 1300),
    ("caller-management.png", "/team/", 1100),
    ("allocations.png", "/allocations/", 1500),
    ("congregation-calling.png", "/calling/congregations/", 1300),
    ("reports.png", "/reports/monthly/", 1700),
    ("audit-history.png", "/audit/", 1200),
]


def new_context(browser, viewport):
    context = browser.new_context(viewport=viewport, color_scheme="light", device_scale_factor=1)
    context.add_init_script("try { localStorage.setItem('ems-theme', 'light'); } catch (e) {}")
    return context


def log_in(page, base, username, password):
    page.goto(f"{base}/accounts/login/")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def capture(page, path, max_height, width):
    height = min(page.evaluate("document.documentElement.scrollHeight"), max_height)
    # A viewport as tall as the shot lets the sticky sidebar fill the whole picture.
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(150)
    page.screenshot(
        path=str(OUT / path), clip={"x": 0, "y": 0, "width": width, "height": height}, full_page=True
    )
    print("saved", path)


def main(base, password):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()

        page = new_context(browser, {"width": 1280, "height": 800}).new_page()
        page.goto(f"{base}/accounts/login/")
        page.wait_for_load_state("networkidle")
        capture(page, "login.png", 800, 1280)

        page = new_context(browser, DESKTOP).new_page()
        log_in(page, base, "demo.coordinator", password)
        for filename, url, max_height in COORDINATOR_PAGES:
            page.set_viewport_size(DESKTOP)
            page.goto(base + url)
            page.wait_for_load_state("networkidle")
            capture(page, filename, max_height, DESKTOP["width"])

        page = new_context(browser, PHONE).new_page()
        log_in(page, base, "asha.demo", password)
        page.goto(f"{base}/my-calls/")
        page.wait_for_load_state("networkidle")
        capture(page, "my-calls.png", 1700, PHONE["width"])
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), sys.argv[2])
