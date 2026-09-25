"""Capture mobile viewport and full-page Mingle reference images."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "reference"


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 412, "height": 915})
        page = context.new_page()
        page.goto((ROOT / "index.html").as_uri() + "#/inbox")
        page.wait_for_function("window.__mingle !== undefined")
        page.evaluate("window.__mingle.reset()")
        page.screenshot(path=OUTPUT / "inbox_viewport.png")

        for page_id in ("inbox", "conversation", "contacts"):
            page.evaluate("id => window.__mingle.navigate(id)", page_id)
            page.wait_for_timeout(80)
            page.add_style_tag(content=(
                ".bottom-nav{position:static!important}"
                ".composer{position:static!important}"
                ".fab{position:absolute!important;bottom:84px!important}"
            ))
            page.screenshot(path=OUTPUT / f"{page_id}_full.png", full_page=True)
            page.reload()
            page.wait_for_function("window.__mingle !== undefined")

        page.evaluate("window.__mingle.openNewChat()")
        page.screenshot(path=OUTPUT / "new_chat_sheet.png")
        page.evaluate("window.__mingle.openAttach()")
        page.screenshot(path=OUTPUT / "attachment_sheet.png")
        page.evaluate("window.__mingle.openClear()")
        page.screenshot(path=OUTPUT / "clear_dialog.png")
        page.evaluate("window.__mingle.navigate('settings')")
        page.screenshot(path=OUTPUT / "settings_viewport.png")
        context.close()
        browser.close()
    for image in sorted(OUTPUT.glob("*.png")):
        print(f"captured {image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
