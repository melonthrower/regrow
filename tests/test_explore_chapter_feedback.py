from copy import deepcopy
import pytest
from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.settlement import SettlementContractError
from .test_operation_centered_settlement import _runtime_for_pending_report_budget
from .test_explore_pending_feedback import _outgoing
from .explore_fixtures import _turn, _known_screen, _png


@pytest.mark.parametrize('changed', ['', 'frame', 'candidate', 'attempt'])
def test_format_error_keeps_only_semantics_of_same_unchanged_candidate(monkeypatch,tmp_path,changed):
    runtime=_runtime_for_pending_report_budget(monkeypatch)
    frame=_png('black');candidate={'regions':[{'name':'Playback','elements':[{'name':'Group'}]}]}
    runtime.report_repair_base=('a1',frame,candidate,None)
    turn=parse_turn(_turn(screen=_known_screen()),has_pending_action=False)
    error=SettlementContractError(code='PARTITION_VISUAL_UNCONFIRMED',field_path='page_report',
        expected='concrete controls',received='different',message='/regions/0/elements/0: split five controls; add missing Title')
    runtime._handle_pending_report_rejection(turn=turn,task=runtime.ledger.tasks['t1'],error=error,screenshot=frame,frame_ref='after.png')
    if changed=='frame':frame=_png('blue')
    if changed=='candidate':runtime.report_repair_base=('a1',frame,{'regions':[]},None)
    if changed=='attempt':
        from dataclasses import replace
        runtime.ledger.attempts['a2']=replace(runtime.ledger.attempts['a1'],attempt_id='a2')
        runtime.pending_attempt_id='a2'
    before=deepcopy(runtime.report_repair_base)
    runtime._handle_pending_report_rejection(turn=turn,task=runtime.ledger.tasks['t1'],
        error=ValueError('page_report_edits requires screen/previous_action/page_report/action=null'),
        screenshot=frame,frame_ref='after.png')
    prompt=_outgoing(runtime,monkeypatch,tmp_path)
    assert ('split five controls' in prompt)==(not changed)
    assert 'screen/previous_action/page_report/action=null' in prompt
    assert runtime._report_budget().count==2
    assert runtime.report_repair_base==before
    assert runtime.ledger.attempts[runtime.pending_attempt_id].outcome=='pending'
