"""Repository layout contracts that keep sources and artifacts discoverable."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_markdown_is_limited_to_maintained_entrypoints() -> None:
    allowed = {"README.md", "CONTRIBUTING.md", "DEPLOY_LOCAL.md", "AGENTS.md"}
    assert {path.name for path in ROOT.glob("*.md")} == allowed


def test_legacy_root_directories_were_moved_to_explicit_boundaries() -> None:
    sources = {
        "downloaded_graphs",
        "desktop_done_20",
        "desktop_impossible_samples",
        "abn_frames_local",
        "clock_issue_visualization_20260520",
        "desktop_done_20_view",
        "settings_audit_20260524",
        "view20",
        "aliyun_collection_upload",
        "aliyun_upload_min",
        "graph-traverse-upload",
        "template_demo",
        "llm_cost",
    }
    assert not {name for name in sources if (ROOT / name).exists()}


def test_canonical_research_docs_and_legacy_targets_exist() -> None:
    required = (
        "research/README.md",
        "research/paper/README.md",
        "research/paper/plans/aaai_ddl_sync_plan.md",
        "research/paper/generated/authority_citation_stats.md",
        "research/paper/references/paper_section_writing_reference.md",
        "research/paper/figures/paper_main_figure_framework.svg",
        "research/history/monitoring/TRAVERSAL_MONITOR_20260516.md",
        "research/history/handoffs/HANDOFF_2026-05-06.md",
        "research/history/sessions/CHANGELOG_session_20260328.md",
        "research/history/agent_prompts/CLAUDE-FABLE-5.md",
        "design/PROJECT_GOAL.md",
        "design/PROJECT_MOTIVATION_MEMORY.md",
        "docs/interactive_debugger.md",
        "data/imported/downloaded_graphs",
        "data/evaluation/desktop_done_20",
        "data/evaluation/desktop_impossible_samples",
        "artifacts/diagnostics/legacy/abn_frames_local",
        "artifacts/archives/legacy/aliyun_collection_upload",
        "artifacts/scratch/legacy/template_demo",
        "artifacts/logs/legacy/llm_cost",
    )
    missing = [relative for relative in required if not (ROOT / relative).exists()]
    assert not missing
    assert not (ROOT / "PROJECT_GOAL.md").exists()


def test_paper_generators_use_repo_relative_output_boundaries() -> None:
    for relative in (
        "tools/inventory_related_work_pdfs.py",
        "tools/extract_related_work_mineru_intros.py",
        "tools/authority_citation_stats.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "Path(__file__).resolve().parents[1]" in source
        assert '"research" / "paper" / "generated"' in source
        assert "C:\\Users\\" not in source
