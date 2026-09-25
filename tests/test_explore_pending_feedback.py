"""Real saved reviewer reasons reach native outgoing requests, not only logs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from gui_rewalk.src.core.explore.agent import OpenAIAPIExplorerAgent
from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.partition_review import verify_partition
from gui_rewalk.src.core.explore.settlement import SettlementContractError
from .explore_fixtures import _known_screen, _png, _turn
from .test_operation_centered_settlement import _runtime_for_pending_report_budget


class RequestCaptured(RuntimeError):
    pass


def _outgoing(runtime, monkeypatch, tmp_path):
    payloads = []
    def capture(*args, **kwargs):
        payloads.append(kwargs['json'])
        raise RequestCaptured()
    monkeypatch.setattr('gui_rewalk.src.core.explore.agent.requests.post', capture)
    agent = OpenAIAPIExplorerAgent(base_url='https://offline.invalid', api_key='fixture',
        model='gpt-5.6-luna', reasoning_effort='medium', output_root=str(tmp_path))
    with pytest.raises(RequestCaptured):
        agent.decide(context=runtime._context(runtime.ledger.tasks['t1'], 'target'),
            screenshots=[_png('white'), _png('black')], has_pending_action=True,
            pending_attempt_id=runtime.pending_attempt_id, corrections=runtime._report_budget())
    return payloads[0]['input'][0]['content'][0]['text']


def test_saved_partition_reasons_reach_request_and_replace_previous_candidate_feedback(monkeypatch, tmp_path):
    cases = json.loads((Path(__file__).parent/'fixtures/explore_partition_feedback.json').read_text())
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    before = deepcopy(runtime.ledger.snapshot())
    old_reason = None
    for count, case in enumerate(cases, 1):
        turn = parse_turn(_turn(screen=_known_screen(), page_report=case['page_report']),
                          has_pending_action=False)
        class Reviewer:
            def review_partition(self, **kwargs):
                return case['review']
        with pytest.raises(SettlementContractError) as caught:
            verify_partition(Reviewer(), report=turn.page_report, screenshot=_png('black'), cache={})
        runtime._handle_pending_report_rejection(turn=turn, task=runtime.ledger.tasks['t1'],
            error=caught.value, screenshot=_png('black'), frame_ref='current.png')
        prompt = _outgoing(runtime, monkeypatch, tmp_path)
        assert case['review']['reason'] in prompt
        if old_reason:
            assert old_reason not in prompt
        old_reason = case['review']['reason']
        assert runtime._report_budget().count == count
        assert 'action must be null' in prompt and 'do not repeat the GUI action' in prompt
        assert 'attempt_ref=a1' in prompt
        assert runtime.pending_attempt_id == 'a1'
        assert runtime.ledger.attempts['a1'].outcome == 'pending'
        assert runtime.actions_used == 1
        for key in ['states', 'operations', 'transitions', 'attempts']:
            assert runtime.ledger.snapshot()[key] == before[key]


@pytest.mark.parametrize('field', ['previous_action.region_effects', 'screen'])
def test_other_classified_errors_keep_detail_and_safety_in_request(monkeypatch, tmp_path, field):
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    error = SettlementContractError(code='FIXTURE_ERROR', field_path=field,
        expected='current evidence', received='bad reference', message='具体引用r999与当前截图不符')
    turn = parse_turn(_turn(screen=_known_screen()), has_pending_action=False)
    runtime._handle_pending_report_rejection(turn=turn, task=runtime.ledger.tasks['t1'], error=error,
        screenshot=_png('black'), frame_ref='current.png')
    prompt = _outgoing(runtime, monkeypatch, tmp_path)
    assert '具体引用r999与当前截图不符' in prompt
    assert 'do not repeat the GUI action' in prompt
    assert runtime.pending_attempt_id == 'a1'


def test_empty_unclassified_error_keeps_conservative_request(monkeypatch, tmp_path):
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    turn = parse_turn(_turn(screen=_known_screen()), has_pending_action=False)
    runtime._handle_pending_report_rejection(turn=turn, task=runtime.ledger.tasks['t1'], error=ValueError(),
        screenshot=_png('black'), frame_ref='current.png')
    prompt = _outgoing(runtime, monkeypatch, tmp_path)
    assert 'UNMAPPED_REPORT_CONTRACT_ERROR' in prompt
    assert '不能根据未分类异常猜测控件身份或成功结果' in prompt
    assert 'do not repeat the GUI action' in prompt
