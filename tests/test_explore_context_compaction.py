"""Keep a global recognition index without resending every detailed page."""
import json

from gui_rewalk.src.core.explore.models import PageState, Transition, ActionAttempt
from gui_rewalk.src.core.explore.status import build_agent_context, known_graph
from .explore_fixtures import _seed_ledger


def context(ledger, task=None, pending=''):
    return build_agent_context(ledger, task, 'target', app_name='fixture', platform='desktop',
                               pending_attempt_id=pending, correction='', rejection_count=0, rejection_limit=4)


def many_states():
    ledger = _seed_ledger()
    for n in range(2, 82):
        sid = f's{n}'
        ledger.states[sid] = PageState(sid, 'p1', f'Panel {n}', f'Detailed observed content for panel {n}. ' * 12, f'{sid}.png', survey_complete=bool(n % 2))
        ledger.pages['p1'].state_ids.append(sid)
        ledger.transitions.append(Transition(f'e{n}', 's1', sid, f'a{n}', {'kind': 'click', 'target': f'Open panel {n}'}, 'opened'))
    return ledger


def test_large_graph_keeps_bounded_local_details_without_global_index():
    ledger = many_states()
    before = ledger.snapshot()
    graph = context(ledger, ledger.operation_task('o1'))['已知页面图']
    assert len(graph['states']) <= 8
    assert 's1' in {s['state_ref'] for s in graph['states']}
    assert 'state_index' not in graph
    assert graph['retrieval']['total_states'] == len(ledger.states)
    assert len(json.dumps(graph, ensure_ascii=False)) < len(json.dumps(known_graph(ledger), ensure_ascii=False)) * .5
    assert ledger.snapshot() == before


def test_pending_return_details_survive_unrelated_history():
    ledger = many_states()
    ledger.current_state_id = 's80'
    ledger.attempts['a-pending'] = ActionAttempt('a-pending', '', 's80', 'recover', {'kind': 'back'}, 'before.png')
    graph = context(ledger, pending='a-pending')['已知页面图']
    states = {s['state_ref']: s for s in graph['states']}
    assert {'s1', 's80'} <= set(states)
    assert states['s1']['known_regions'][0]['region_ref'] == 'r1'
    assert graph['connections'] == [{'from': 's1', 'to': 's80', 'action': 'Open panel 80'}]


def test_away_context_does_not_dump_unrelated_connections():
    ledger = many_states()
    ledger.current_state_id = 's2'
    graph = context(ledger, ledger.operation_task('o1'))['已知页面图']
    assert len(graph['connections']) <= 8
    assert any(e['from'] == 's1' and e['to'] == 's2' for e in graph['connections'])
    assert 's1' in {s['state_ref'] for s in graph['states']}


def test_current_controls_and_pending_receipt_are_not_shortened():
    ledger = many_states()
    task = ledger.operation_task('o1')
    normal = context(ledger, task)
    assert normal['当前页面已登记内容']['regions'][0]['elements'][0]['element_ref'] == 'el1'
    ledger.attempts['a-pending'] = ActionAttempt('a-pending', task.task_id, 's1', 'execute',
        {'kind': 'input_text', 'operation_ref': 'o1', 'owner_ref': 'el1', 'target': 'Exact field', 'text': 'literal value'}, 'before.png')
    pending = context(ledger, task, 'a-pending')
    assert pending['待结算动作详情']['text'] == 'literal value'
    assert pending['待结算动作详情']['owner_ref'] == 'el1'
    assert pending['当前页面已登记内容'] == {}


def test_prompt_serialization_removes_whitespace_without_changing_values():
    from gui_rewalk.src.core.explore.prompts import build_user_prompt
    value = context(many_states())
    value['exact_text'] = 'literal  spaces\nand newlines 保留'
    rendered = build_user_prompt(value)
    body = rendered.split('\n', 1)[1]
    assert json.loads(body) == value
    assert len(body) < len(json.dumps(value, ensure_ascii=False, indent=2)) * .85
