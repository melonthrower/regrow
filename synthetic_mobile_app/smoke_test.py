"""Headless interaction smoke test for the Mingle mobile fixture."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent


def action(page, action_id: str):
    return page.locator(f'[data-action-id="{action_id}"]')


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 412, "height": 915})
        page.goto((ROOT / "index.html").as_uri() + "#/inbox")
        page.wait_for_function("window.__mingle !== undefined")
        page.evaluate("window.__mingle.reset()")

        action(page, "inbox.new_chat").click()
        assert page.locator('[data-surface-kind="bottom_sheet"]').is_visible()
        action(page, "new_chat.close").click()

        action(page, "inbox.open_weekend").click()
        page.wait_for_function("location.hash === '#/conversation'")
        assert page.evaluate("document.documentElement.scrollHeight > innerHeight * 1.4")
        action(page, "conversation.info").click()
        action(page, "chat_info.mute").click()
        assert action(page, "chat_info.mute").get_attribute("aria-pressed") == "true"
        action(page, "chat_info.clear").click()
        assert page.locator('[data-surface-kind="dialog"]').is_visible()
        action(page, "clear.cancel").click()
        action(page, "chat_info.back").click()

        action(page, "conversation.attach").click()
        assert page.get_by_text("Share with Weekend Plan", exact=True).is_visible()
        action(page, "attach.close").click()
        action(page, "conversation.send").click()
        assert page.evaluate("window.__mingle.snapshot().state.messageSent") is True
        page.get_by_text("Sounds good", exact=False).wait_for()
        action(page, "conversation.back").click()

        action(page, "inbox.nav_contacts").click()
        action(page, "contacts.open_alex").click()
        action(page, "contact.favorite").click()
        assert action(page, "contact.favorite").get_attribute("aria-pressed") == "true"
        action(page, "contact.message").click()
        page.wait_for_function("location.hash === '#/conversation'")

        page.evaluate("window.__mingle.navigate('profile')")
        action(page, "profile.settings").click()
        before = page.evaluate("window.__mingle.snapshot().state.notifications")
        action(page, "settings.notifications_toggle").click()
        after = page.evaluate("window.__mingle.snapshot().state.notifications")
        assert before is True and after is False
        browser.close()
    print("PASS Mingle mobile navigation/state/overlay/scroll smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
