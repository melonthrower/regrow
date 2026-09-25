from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from playwright.sync_api import Page, sync_playwright
import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "traversal_test_app"


def _oracle() -> dict:
    return json.loads((FIXTURE / "oracle.json").read_text(encoding="utf-8"))


def _edge_cases() -> dict:
    return json.loads(
        (FIXTURE / "edge_cases.json").read_text(encoding="utf-8"))


def _open(page: Page, filename: str, route: str = "") -> None:
    page.goto((FIXTURE / filename).as_uri() + route)
    page.wait_for_function("() => Boolean(window.__fixture)")


def test_truth_points_to_nine_small_standalone_pages() -> None:
    oracle = _oracle()
    assert oracle["app_id"] == "quick_traversal_tests"
    assert [item["file"] for item in oracle["scenarios"]] == [
        "scroll.html",
        "loop.html",
        "back.html",
        "region_merge.html",
        "panel_combinations.html",
        "notion_like_desktop.html",
        "gmail_like_desktop.html",
        "spotify_like_desktop.html",
        "maps_like_mobile.html",
    ]
    for filename in (
        "index.html", "scroll.html", "loop.html", "back.html",
        "region_merge.html",
        "panel_combinations.html",
        "notion_like_desktop.html",
        "gmail_like_desktop.html",
        "spotify_like_desktop.html",
        "maps_like_mobile.html",
    ):
        assert (FIXTURE / filename).is_file()


def test_target_edge_cases_are_small_exact_button_checks() -> None:
    payload = _edge_cases()
    cases = payload["cases"]
    assert payload["schema"] == "gui_rewalk.target_edge_cases.v1"
    assert len(cases) == 20
    assert len({item["id"] for item in cases}) == len(cases)
    assert {item["file"] for item in cases} == {
        "scroll.html", "loop.html", "back.html", "region_merge.html",
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for item in cases:
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            _open(page, item["file"], item["start_hash"])
            labels = page.locator("button").all_inner_texts()
            assert labels.count(item["target"]) == 1, item["id"]
            assert item["source_page"] == page.locator("h1").inner_text()
            page.close()
        browser.close()


@pytest.mark.parametrize(("script_name", "case_prefix", "expected_count"), [
    ("test_scroll.ps1", "scroll_", 3),
    ("test_loop.ps1", "loop_", 4),
    ("test_back.ps1", "back_", 6),
    ("test_region_merge.ps1", "merge_", 7),
])
def test_dedicated_fixture_scripts_list_only_their_own_edges(
    script_name: str, case_prefix: str, expected_count: int,
) -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    script = FIXTURE / "scripts" / script_name
    assert script.is_file()

    result = subprocess.run(
        [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-ListCases",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == expected_count
    assert all(line.startswith(case_prefix) for line in lines)


def test_scroll_page_has_three_independent_hidden_entries() -> None:
    truth = _oracle()["scenarios"][0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        _open(page, truth["file"])
        assert page.evaluate("document.scrollingElement.scrollHeight === innerHeight")

        initial = page.evaluate("""
            () => Object.fromEntries([...document.querySelectorAll('[data-scroll-region-id]')].map(node => {
              const button = node.querySelector('[data-region-entry]');
              return [node.dataset.scrollRegionId, {
                top: node.scrollTop,
                hidden: button.getBoundingClientRect().top >= node.getBoundingClientRect().bottom,
                scrollable: node.scrollHeight > node.clientHeight
              }];
            }))
        """)
        assert set(initial) == {item["id"] for item in truth["regions"]}
        assert all(item["top"] == 0 and item["hidden"] and item["scrollable"] for item in initial.values())

        offsets = []
        for region in truth["regions"]:
            page.eval_on_selector_all("[data-scroll-region-id]", "nodes => nodes.forEach(node => node.scrollTop = 0)")
            button = page.locator(f'[data-region-entry="{region["entry_id"]}"]')
            button.scroll_into_view_if_needed()
            positions = page.evaluate("""
                () => Object.fromEntries([...document.querySelectorAll('[data-scroll-region-id]')]
                  .map(node => [node.dataset.scrollRegionId, node.scrollTop]))
            """)
            assert positions[region["id"]] > 0
            assert all(value == 0 for key, value in positions.items() if key != region["id"])
            offsets.append(positions[region["id"]])
        assert offsets == sorted(offsets)
        browser.close()


def test_scroll_entries_reveal_function_content_inside_their_own_container() -> None:
    expected = {
        "scroll.today.open_notes": "Focus notes",
        "scroll.projects.open_plan": "Launch plan",
        "scroll.files.open_archive": "Research archive",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        _open(page, "scroll.html")
        for entry_id, title in expected.items():
            button = page.locator(f'[data-region-entry="{entry_id}"]')
            button.scroll_into_view_if_needed()
            button.click()
            result = page.locator(f'[data-entry-result="{entry_id}"]')
            assert result.is_visible()
            assert result.locator("strong").inner_text() == title
        assert page.locator("[data-entry-result][data-open=true]").count() == 3
        browser.close()


def test_loop_is_short_and_returns_to_the_same_page1() -> None:
    truth = _oracle()["scenarios"][1]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        _open(page, truth["file"], "#/1")
        signature = page.locator("main").get_attribute("data-page-signature")
        headings = [page.locator("h1").inner_text()]
        page.locator('[data-action-id="loop.page1.next"]').click()
        page.wait_for_function(
            "() => window.__fixture.snapshot().pageId === 'loop.order_detail'"
        )
        headings.append(page.locator("h1").inner_text())

        target = page.locator('[data-action-id="loop.page2.next"]')
        assert target.bounding_box()["y"] >= page.evaluate("innerHeight")
        target.scroll_into_view_if_needed()
        target.click()
        page.wait_for_function(
            "() => window.__fixture.snapshot().pageId === 'loop.delivery_journey'"
        )
        headings.append(page.locator("h1").inner_text())
        page.locator('[data-action-id="loop.page3.next"]').click()
        page.wait_for_function(
            "() => window.__fixture.snapshot().pageId === 'loop.courier_profile'"
        )
        headings.append(page.locator("h1").inner_text())
        page.locator('[data-action-id="loop.page4.return"]').click()
        page.wait_for_function(
            "() => window.__fixture.snapshot().pageId === 'loop.orders'"
        )
        headings.append(page.locator("h1").inner_text())

        snapshot = page.evaluate("window.__fixture.snapshot()")
        assert snapshot["visits"] == truth["page_chain"]
        assert headings == truth["page_titles"]
        assert all("Page " not in heading for heading in headings)
        assert page.locator("main").get_attribute("data-page-signature") == signature
        browser.close()


def test_back_pages_are_fully_connected_and_return_to_each_entry_source() -> None:
    truth = _oracle()["scenarios"][2]
    page_by_route = {item["route"]: item for item in truth["pages"]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for edge in truth["direct_edges"]:
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            _open(
                page,
                truth["file"],
                f'?edge={edge["entry_id"]}#{edge["source"]}',
            )

            back = page.locator("#back")
            assert back.is_enabled() is False
            expected_source_edges = {
                item["entry_id"]
                for item in truth["direct_edges"]
                if item["source"] == edge["source"]
            }
            actual_source_edges = set(page.evaluate("""
                () => [...document.querySelectorAll('[data-action-id]')]
                  .map(node => node.dataset.actionId)
            """))
            assert actual_source_edges == expected_source_edges

            entry = page.locator(f'[data-action-id="{edge["entry_id"]}"]')
            entry.scroll_into_view_if_needed()
            source_scroll = page.evaluate("scrollY")
            assert source_scroll > 0
            entry.click()

            target_page = page_by_route[edge["target"]]
            source_page = page_by_route[edge["source"]]
            page.wait_for_function(
                "expected => window.__fixture.snapshot().pageId === expected",
                arg=target_page["page_id"],
            )
            assert back.is_enabled() is True
            assert back.inner_text() == "← Back"

            back.click()
            page.wait_for_function(
                "expected => window.__fixture.snapshot().pageId === expected",
                arg=source_page["page_id"],
            )
            page.wait_for_function(
                "expected => Math.abs(scrollY - expected) <= 2",
                arg=source_scroll,
            )
            assert back.is_enabled() is False
            page.close()
        browser.close()


def test_shared_regions_keep_semantics_and_button_geometry_while_moving() -> None:
    truth = _oracle()["scenarios"][3]
    page_truth = {item["key"]: item for item in truth["pages"]}
    region_truth = {item["stable_id"]: item for item in truth["regions"]}
    absolute_positions = {stable_id: [] for stable_id in region_truth}
    relative_buttons = {stable_id: [] for stable_id in region_truth}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        for expected_page in truth["pages"]:
            _open(page, truth["file"], f'#{expected_page["route"]}')
            assert page.locator("h1").inner_text() == expected_page["title"]
            assert page.evaluate("window.__fixture.snapshot().pageId") == (
                expected_page["page_id"])
            body_text = page.locator("body").inner_text()
            assert all(label not in body_text for label in (
                "Region A", "Region B", "Region C", "Region D",
            ))

            occurrences = page.locator("[data-region-id]")
            actual_ids = occurrences.evaluate_all(
                "nodes => nodes.map(node => node.dataset.regionId)")
            expected_ids = [
                item["stable_id"] for item in truth["regions"]
                if any(
                    occurrence["page"] == expected_page["key"]
                    for occurrence in item["occurrences"]
                )
            ]
            assert set(actual_ids) == set(expected_ids)

            for stable_id in actual_ids:
                card = page.locator(
                    f'[data-region-id="{stable_id}"]')
                button = card.locator("button")
                card_box = card.bounding_box()
                button_box = button.bounding_box()
                assert card_box and button_box
                absolute_positions[stable_id].append((
                    round(card_box["x"]), round(card_box["y"]),
                ))
                relative_buttons[stable_id].append(tuple(round(value, 4) for value in (
                    (button_box["x"] - card_box["x"]) / card_box["width"],
                    (button_box["y"] - card_box["y"]) / card_box["height"],
                    button_box["width"] / card_box["width"],
                    button_box["height"] / card_box["height"],
                )))
                expected_region = region_truth[stable_id]
                assert card.locator("h2").inner_text() == expected_region["title"]
                assert button.inner_text() == expected_region["entry"]

        assert sum(map(len, absolute_positions.values())) == (
            truth["contract"]["expected_region_occurrence_count"])
        assert len(absolute_positions) == (
            truth["contract"]["expected_stable_region_count"])
        for expected_region in truth["regions"]:
            stable_id = expected_region["stable_id"]
            if len(expected_region["occurrences"]) > 1:
                assert len(set(absolute_positions[stable_id])) > 1
                assert len(set(relative_buttons[stable_id])) == 1

        for expected_region in truth["regions"]:
            for occurrence in expected_region["occurrences"]:
                source = page_truth[occurrence["page"]]
                _open(page, truth["file"], f'#{source["route"]}')
                page.locator(
                    f'[data-action-id="{expected_region["entry_id"]}"]'
                ).click()
                destination = next(
                    item for item in truth["pages"]
                    if item["route"] == expected_region["destination"])
                page.wait_for_function(
                    "expected => window.__fixture.snapshot().pageId === expected",
                    arg=destination["page_id"],
                )
        page.close()
        browser.close()


def test_panel_combinations_reuse_page_identity_across_region_changes() -> None:
    truth = _oracle()["scenarios"][4]
    expected_pages = {item["page_id"] for item in truth["pages"]}
    sequence = truth["guided_sequence"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        _open(page, truth["file"], "#/home")

        initial = page.evaluate("window.__fixture.snapshot()")
        assert initial["pageId"] == "combo.home"
        assert initial["regions"] == [
            "combo.toolbar", "combo.navigation", "combo.main.home",
            "combo.status"]

        observed_pages = [initial["pageId"]]
        for step in sequence:
            page.locator(
                f'[data-action-id="{step["action_id"]}"]'
            ).click()
            page.wait_for_function(
                "expected => document.body.dataset.pageId === expected",
                arg=step["target_page"],
            )
            snapshot = page.evaluate("window.__fixture.snapshot()")
            observed_pages.append(snapshot["pageId"])
            assert snapshot["regions"] == step["regions"]

        final = page.evaluate("window.__fixture.snapshot()")
        assert set(observed_pages) == expected_pages
        assert observed_pages == [
            "combo.home", "combo.records", "combo.analytics",
            "combo.analytics", "combo.settings", "combo.home",
        ]
        assert final["pageId"] == initial["pageId"]
        assert final["regions"] != initial["regions"]
        assert "combo.library" in final["regions"]
        assert "combo.inspector" in final["regions"]
        assert "combo.review-sheet" not in final["regions"]

        visits = final["visits"]
        assert _contains_subsequence_for_fixture(
            visits,
            ["combo.home", "combo.records", "combo.analytics",
             "combo.settings", "combo.home"],
        )
        browser.close()


@pytest.mark.parametrize(("scenario_index", "viewport"), [
    (5, {"width": 1365, "height": 900}),
    (6, {"width": 1365, "height": 900}),
    (7, {"width": 1365, "height": 900}),
    (8, {"width": 430, "height": 900}),
])
def test_real_app_style_fixtures_separate_pages_from_surfaces(
    scenario_index: int,
    viewport: dict[str, int],
) -> None:
    truth = _oracle()["scenarios"][scenario_index]
    expected_pages = {item["page_id"] for item in truth["pages"]}
    sequence = truth["guided_sequence"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport)
        _open(page, truth["file"], truth["start_hash"])

        initial = page.evaluate("window.__fixture.snapshot()")
        assert initial["pageId"] == truth["expected_page_sequence"][0]
        assert initial["regions"] == truth["initial_regions"]
        assert all(
            page.locator(f'[data-region-id="{region_id}"]').is_visible()
            for region_id in initial["regions"]
        )

        observed_pages = [initial["pageId"]]
        observed_regions = set(initial["regions"])
        for step in sequence:
            page.locator(
                f'[data-action-id="{step["action_id"]}"]'
            ).click()
            page.wait_for_function(
                "expected => document.body.dataset.pageId === expected",
                arg=step["target_page"],
            )
            snapshot = page.evaluate("window.__fixture.snapshot()")
            observed_pages.append(snapshot["pageId"])
            assert snapshot["regions"] == step["regions"]
            assert all(
                page.locator(f'[data-region-id="{region_id}"]').is_visible()
                for region_id in step["regions"]
            )
            observed_regions.update(snapshot["regions"])

        assert set(observed_pages) == expected_pages
        assert observed_pages == truth["expected_page_sequence"]
        assert len(observed_regions) == (
            truth["contract"]["expected_canonical_region_count"])
        browser.close()


def test_gmail_like_send_has_visible_local_result() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        _open(page, "gmail_like_desktop.html", "#/inbox")
        page.locator('[data-action-id="mail.compose.open"]').click()
        page.locator('[data-action-id="mail.compose.send"]').click()

        assert page.locator("#compose-backdrop").is_visible() is False
        assert page.locator("#sent-toast").is_visible() is True
        assert page.locator("#sent-toast").inner_text() == "Message sent"
        assert page.evaluate("window.__fixture.snapshot().pageId") == "mail.inbox"
        browser.close()


def test_maps_like_secondary_actions_have_visible_local_results() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 430, "height": 900})
        _open(page, "maps_like_mobile.html", "#/explore")
        page.locator('[data-action-id="maps.search.open"]').click()
        page.locator('[data-action-id="maps.results.harbor"]').click()
        page.locator('[data-action-id="maps.place.save"]').click()
        assert page.locator("#feedback").inner_text() == "Saved to Favorites"

        page.locator('[data-action-id="maps.place.directions"]').click()
        page.locator('[data-action-id="maps.route.drive"]').click()
        assert page.locator("#feedback").inner_text() == (
            "Driving route selected")

        page.locator('[data-action-id="maps.nav.saved"]').click()
        page.locator('[data-action-id="maps.saved.open-harbor"]').click()
        page.locator('[data-action-id="maps.place.call"]').click()
        assert page.locator("#feedback").inner_text() == "Call preview ready"
        browser.close()


def _contains_subsequence_for_fixture(values: list[str], expected: list[str]) -> bool:
    index = 0
    for value in values:
        if index < len(expected) and value == expected[index]:
            index += 1
    return index == len(expected)
