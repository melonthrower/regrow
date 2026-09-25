"""Offline contracts for the canonical visual-traversal prompt catalog."""

from __future__ import annotations

import re
from pathlib import Path

from gui_rewalk.src.core.visual_traversal import visual_perception
from gui_rewalk.src.core.visual_traversal.agents import effects, focus, interruption, review
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    ANNOTATION_REVIEW_PROMPT,
    ANNOTATION_REVIEW_WITH_REGIONS_PROMPT,
    VLM_GROUNDING_PROMPT,
    VLM_NAMING_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.prompts.navigation import (
    INTERRUPTION_DISMISS_PROMPT,
    STATEFUL_RISK_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.prompts.identity_candidates import (
    build_page_candidate_selection_prompt,
    build_region_correspondence_prompt,
    build_region_partition_mapping_prompt,
    build_pair_page_identity_prompt,
)
from gui_rewalk.src.core.visual_traversal.prompts.block_inventory import (
    PAGE_MAP_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.prompts.interface_scope import (
    CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
    REGION_PRESENTATION_DEFINITION_ZH,
)


def test_consumers_use_catalog_objects() -> None:
    assert visual_perception.VLM_NAMING_PROMPT is VLM_NAMING_PROMPT
    assert visual_perception.VLM_GROUNDING_PROMPT is VLM_GROUNDING_PROMPT
    assert interruption.INTERRUPTION_DISMISS_PROMPT is INTERRUPTION_DISMISS_PROMPT
    assert review.ANNOTATION_REVIEW_PROMPT is ANNOTATION_REVIEW_PROMPT
    assert (
        review.ANNOTATION_REVIEW_WITH_REGIONS_PROMPT
        is ANNOTATION_REVIEW_WITH_REGIONS_PROMPT
    )
    assert effects.STATEFUL_RISK_PROMPT is STATEFUL_RISK_PROMPT


def test_app_focus_uses_only_system_foreground_metadata(monkeypatch) -> None:
    verdicts = iter((True, False, None))
    monkeypatch.setattr(
        focus, "is_app_foreground", lambda _env, _app: next(verdicts))
    guard = focus.AppFocusGuard(
        object(), "Mingle", is_touch=True)

    assert guard.on_app(b"ignored screenshot") is True
    assert guard.last_kind == "on_app"
    assert guard.on_app(b"ignored screenshot") is False
    assert guard.last_kind == "external_app"
    assert guard.on_app(b"ignored screenshot") is None
    assert guard.last_kind == "unknown"

    root = Path(__file__).resolve().parents[1]
    prompt_catalog = (
        root / "gui_rewalk/src/core/visual_traversal/prompts/navigation.py"
    ).read_text(encoding="utf-8")
    focus_source = (
        root / "gui_rewalk/src/core/visual_traversal/agents/focus.py"
    ).read_text(encoding="utf-8")
    assert "APP_FOCUS_PROMPT" not in prompt_catalog
    assert "predict_mm_role" not in focus_source
    assert '"app_focus"' not in focus_source


def test_page_identity_prompts_expose_only_the_visual_judgment() -> None:
    pair_prompt = build_pair_page_identity_prompt()
    lowered = pair_prompt.lower()
    assert "只输出" in lowered and "json" in lowered
    for internal_term in (
        "page_id",
        "state_id",
        "variant_id",
        "persistent id",
        "framework-owned",
    ):
        assert internal_term not in lowered
    assert "图1" in pair_prompt and "图2" in pair_prompt
    assert CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH in pair_prompt
    assert "同一页面处于不同滚动位置时仍属于同一个页面" in pair_prompt
    assert "先检查图2是否出现不属于目标应用的临时前景内容" in pair_prompt
    assert "same_state" not in pair_prompt
    assert "same_page_variant" not in pair_prompt
    assert "different_page" not in pair_prompt


def test_page_candidate_prompt_only_shortlists_and_prepares_a_name() -> None:
    prompt = build_page_candidate_selection_prompt(
        [{
            "candidate_page_id": "C1",
            "page": {
                "interface_name": "Users",
                "regions": [{
                    "name": "Authentication",
                    "description": "Account access settings",
                }],
            },
        }],
        has_source_screenshot=True,
        opening_action={"label": "Open users", "clicked_point": [10, 20]},
    )

    assert "图1是当前完整截图" in prompt
    assert "来源页面，只用于理解到达路径和命名" in prompt
    assert CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH in prompt
    assert "不能仅因为由此前动作产生" in prompt
    assert "不属于当前操作界面的内容不参与页面匹配或命名" in prompt
    for hardcoded_example in ("Tooltip", "悬停标签", "Toast"):
        assert hardcoded_example not in CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH
    assert "备用名称只命名上述当前操作界面" in prompt
    assert "不属于当前操作界面的任何可见内容不得出现在备用名称中" in prompt
    assert "最多两个" in prompt
    assert '"candidate_page_ids":["C1"]' in prompt
    assert "至少一个、最多两个，不得为空" in prompt
    assert "即使当前截图看起来属于新页面" in prompt
    assert "通用窗口管理控件" in PAGE_MAP_PROMPT
    assert "应用自身提供的导航栏、工具栏或操作栏" in PAGE_MAP_PROMPT
    assert '"proposed_new_page_name":"..."' in prompt
    assert "最终是否与候选属于同一页面" in prompt
    assert "与已登记页面名称有清楚差异" in prompt
    assert "不需要与已登记页面名称保持唯一" not in prompt
    for internal_term in (
        "explorer", "observer", "grounder", "state_id", "variant_id",
    ):
        assert internal_term not in prompt.casefold()


def test_page_map_and_region_mapping_use_their_confirmed_task_local_prompts() -> None:
    from gui_rewalk.src.core.visual_traversal.prompts.block_inventory import (
        PAGE_MAP_PROMPT,
    )

    assert CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH not in PAGE_MAP_PROMPT
    assert "当前唯一的 active interaction surface" in PAGE_MAP_PROMPT
    assert "Region 是功能容器，不是单个操作目标" in PAGE_MAP_PROMPT

    legacy = build_region_correspondence_prompt("A", [], "B", [])
    assert CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH in legacy
    mapped = build_region_partition_mapping_prompt("A", [], "B", [])
    assert CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH not in mapped
    assert REGION_PRESENTATION_DEFINITION_ZH not in mapped
    assert "对应关系只表示同一内容容器或同一对象身份" in mapped


def test_retired_region_prompt_roles_are_not_in_the_runtime_catalog() -> None:
    from gui_rewalk.src.core.visual_traversal import prompts
    from gui_rewalk.src.core.visual_traversal.prompts import grounding

    assert not hasattr(grounding, "BLOCK_SEGMENTATION_PROMPT")
    assert not hasattr(grounding, "REGION_LONG_INVENTORY_PROMPT")
    assert not hasattr(prompts, "build_page_name_disambiguation_prompt")
    root = Path(__file__).resolve().parents[1]
    runtime_source = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "gui_rewalk/src/core/visual_traversal/grounding/region/scroll.py",
            "gui_rewalk/src/core/visual_traversal/visual_perception.py",
        )
    )
    assert '"region_segmentation"' not in runtime_source
    assert '"region_long_inventory"' not in runtime_source
    identity_source = (
        root / "gui_rewalk/src/core/visual_traversal/agents/identity.py"
    ).read_text(encoding="utf-8")
    assert '"page_name_disambiguation"' not in identity_source


def test_consumers_do_not_redeclare_prompt_constants() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "gui_rewalk/src/core/visual_traversal/agents/focus.py",
        "gui_rewalk/src/core/visual_traversal/agents/interruption.py",
        "gui_rewalk/src/core/visual_traversal/agents/review.py",
        "gui_rewalk/src/core/visual_traversal/agents/effects.py",
        "gui_rewalk/src/core/visual_traversal/visual_perception.py",
        "gui_rewalk/src/core/visual_traversal/visual_engine.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*_[A-Z0-9_]*PROMPT\s*[+]?=", source)
