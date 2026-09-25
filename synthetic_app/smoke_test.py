"""Headless browser smoke test for fixture navigation, state, overlays, and scroll."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        page.goto((ROOT / "index.html").as_uri() + "#/home")
        page.wait_for_function("window.__fixture !== undefined")
        page.evaluate("window.__fixture.reset()")

        page.get_by_role("button", name="Browse documents").click()
        page.wait_for_function("location.hash === '#/library'")
        page.get_by_role("button", name="Open Document 09").wait_for(state="attached")
        assert page.evaluate("document.documentElement.scrollHeight > innerHeight * 1.4")
        page.get_by_role("button", name="Open Document 09").scroll_into_view_if_needed()
        page.get_by_role("button", name="Open Document 09").click()
        page.wait_for_function("location.hash === '#/record_detail'")
        assert "New hire handbook" in page.locator("main").inner_text()

        page.get_by_role("button", name="Mark reviewed").click()
        assert page.get_by_role("button", name="Mark unreviewed").get_attribute(
            "aria-pressed"
        ) == "true"
        page.get_by_role("button", name="Back to documents").click()

        page.get_by_role("button", name="Activity").click()
        page.wait_for_function("location.hash === '#/activity'")
        page.get_by_role("button", name="View weekly summary").scroll_into_view_if_needed()
        page.get_by_role("button", name="View weekly summary").click()
        page.get_by_role("button", name="Archive weekly summary").click()
        assert page.locator('[data-surface-kind="dialog"]').is_visible()
        page.get_by_role("button", name="Cancel").click()
        assert page.locator('[data-surface-kind="dialog"]').count() == 0
        page.get_by_role("button", name="Archive weekly summary").click()
        page.get_by_role("button", name="Archive summary").click()
        page.wait_for_function("location.hash === '#/done'")
        page.get_by_text("Your workspace is ready for a fresh week.").wait_for(
            state="visible"
        )

        page.evaluate("window.__fixture.navigate('settings')")
        before = page.evaluate("window.__fixture.snapshot().state.dailyTips")
        page.get_by_role("button", name="Off").click()
        after = page.evaluate("window.__fixture.snapshot().state.dailyTips")
        assert before is False and after is True
        browser.close()
    print("PASS Dayline navigation/state/overlay/scroll smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
