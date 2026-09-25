"""Capture deterministic viewport and full-page reference images with Playwright."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reference"


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app_url = (ROOT / "index.html").as_uri()
    inspector_url = (ROOT / "inspector.html").as_uri()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1365, "height": 900})
        page = context.new_page()
        page.goto(app_url + "#/home")
        page.wait_for_function("window.__fixture !== undefined")
        page.evaluate("window.__fixture.reset()")
        page.wait_for_timeout(150)
        page.screenshot(path=OUTPUT / "home_viewport.png")

        for page_id in ("library", "activity", "about"):
            page.evaluate("pageId => window.__fixture.navigate(pageId)", page_id)
            page.wait_for_timeout(150)
            page.screenshot(path=OUTPUT / f"{page_id}_full.png", full_page=True)

        page.evaluate("window.__fixture.navigate('home')")
        page.evaluate("window.__fixture.openMenu()")
        page.wait_for_timeout(100)
        page.screenshot(path=OUTPUT / "popup_menu_viewport.png")

        page.evaluate("window.__fixture.navigate('coverage_report')")
        page.evaluate("window.__fixture.openConfirm()")
        page.wait_for_timeout(100)
        page.screenshot(path=OUTPUT / "confirm_dialog_viewport.png")

        page.goto(inspector_url)
        page.wait_for_timeout(150)
        page.screenshot(path=OUTPUT / "oracle_inspector_full.png", full_page=True)
        context.close()
        browser.close()
    for image in sorted(OUTPUT.glob("*.png")):
        print(f"captured {image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
