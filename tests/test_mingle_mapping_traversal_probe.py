from pathlib import Path

from tools.run_mingle_mapping_traversal_probe import (
    build_command,
    count_reviewed_groundings,
    find_prompt_local_identity_refs,
    summarize,
)


def test_command_defaults_to_real_inventory_and_grounding(tmp_path: Path) -> None:
    command = build_command(result_dir=tmp_path, max_actions=3, max_states=2)
    joined = " ".join(command)

    assert "--vm_provider local_html" in joined
    assert "--fixture_oracle_inventory off" in joined
    assert "--fixture_oracle_grounding off" in joined
    assert "--max_actions 3" in joined
    assert "--max_states 2" in joined
    assert "--headless" in command
    assert "--no_return_path_verify" not in command


def test_command_can_isolate_with_fixture_inventory(tmp_path: Path) -> None:
    command = build_command(result_dir=tmp_path, inventory_source="fixture")

    assert "--fixture_oracle_inventory on" in " ".join(command)
    assert "--fixture_oracle_grounding off" in " ".join(command)


def test_command_can_disable_proactive_return_probe(tmp_path: Path) -> None:
    command = build_command(result_dir=tmp_path, return_policy="lazy")

    assert "--no_return_path_verify" in command


def test_prompt_local_ids_are_checked_only_in_identity_fields() -> None:
    graph = {
        "nodes": [{"id": "c0", "description": "text may mention c1"}],
        "action_edges": [{"element_id": "v2", "detail": "choice c3"}],
    }

    assert find_prompt_local_identity_refs(graph) == [
        {"path": "nodes[0].id", "value": "c0"},
        {"path": "action_edges[0].element_id", "value": "v2"},
    ]


def test_summary_passes_for_real_calls_and_verified_mapped_landing() -> None:
    graph = {
        "nodes": [{"id": "state_a"}, {"id": "state_b"}],
        "action_edges": [
            {
                "action_edge_id": "ae_1",
                "element_id": "e_42",
                "attempts": [
                    {
                        "attempt_id": "mingle:1",
                        "source": "state_a",
                        "target": "state_b",
                        "element_id": "e_42",
                        "element_label": "Open Weekend Plan",
                        "committed": True,
                        "landing_verified": True,
                        "outcome": "new_state",
                    }
                ],
            }
        ],
    }
    ledger = {
        "roles": {
            "explorer": {"calls": 1},
            "target_grounding": {"calls": 1},
            "target_review": {"calls": 1},
        }
    }

    summary = summarize(
        graph,
        ledger,
        traversal_return_code=0,
        graph_path=Path("graph.json"),
        reviewed_groundings=1,
    )

    assert summary["status"] == "pass"
    assert summary["counts"]["verified_landing_attempts"] == 1
    assert summary["verified_actions"][0]["element_id"] == "e_42"
    assert summary["vlm_calls"]["roles"]["target_grounding"] == 1


def test_formal_grounding_requires_recorded_reviewer_acceptance() -> None:
    graph = {
        "nodes": [{"id": "state_a"}, {"id": "state_b"}],
        "action_edges": [
            {
                "element_id": "e1",
                "attempts": [
                    {
                        "element_id": "e1",
                        "committed": True,
                        "landing_verified": True,
                    }
                ],
            }
        ],
    }
    ledger = {
        "roles": {
            "explorer": {"calls": 1},
            "target_grounding": {"calls": 1},
            "target_review": {"calls": 1},
        }
    }

    summary = summarize(
        graph,
        ledger,
        traversal_return_code=0,
        graph_path=Path("graph.json"),
        reviewed_groundings=1,
    )

    assert summary["status"] == "pass"
    assert summary["checks"]["target_reviewer_called"] is True
    assert summary["checks"]["reviewer_accepted_grounding_recorded"] is True


def test_count_reviewed_groundings(tmp_path: Path) -> None:
    attempt = tmp_path / "target_grounding_attempts" / "0001"
    attempt.mkdir(parents=True)
    (attempt / "result.json").write_text(
        '{"reviewer":{"accepted":true,"status":"target_review_accepted"}}',
        encoding="utf-8",
    )

    assert count_reviewed_groundings(tmp_path) == 1


def test_summary_fails_when_choice_id_leaks_or_grounding_is_missing() -> None:
    graph = {
        "nodes": [{"id": "state_a"}],
        "action_edges": [
            {
                "element_id": "c0",
                "attempts": [
                    {
                        "attempt_id": "mingle:1",
                        "source": "state_a",
                        "target": "state_a",
                        "element_id": "c0",
                        "committed": True,
                        "landing_verified": True,
                    }
                ],
            }
        ],
    }
    ledger = {
        "roles": {
            "explorer": {"calls": 1},
            "target_grounding": {"calls": 0},
            "target_review": {"calls": 1},
        }
    }

    summary = summarize(
        graph,
        ledger,
        traversal_return_code=0,
        graph_path=Path("graph.json"),
    )

    assert summary["status"] == "fail"
    assert summary["checks"]["real_target_grounding_called"] is False
    assert summary["checks"]["no_prompt_local_identity_persisted"] is False
