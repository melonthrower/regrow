"""Map references must preserve provenance, task contracts and failed intent."""
from copy import deepcopy
import json
from pathlib import Path
from tests.test_recovery_discovery import mod
from tests.test_current_page_context import case
from tests.test_action_correction_single_frame import job, ROOT


def mapped_case(tmp_path):
    records, state, frame = case(tmp_path)
    task = records['world']['tasks']['inspect']
    task.update(reason='Inspect direct feedback only', action='click', result_evidence='Still pending')
    text, evidence = mod('history_context').action_context(records, state, 'world', 'inspect', task)
    q = {'action_ready': True, 'system_prompt': 'Original rules', 'user_prompt': text,
         'context_evidence': evidence, 'source': {'region': 'world', 'task_region': 'world',
         'task_name': 'inspect', 'observation': 'opened'}, 'screenshots': [str(frame)],
         'image_refs': [str(frame)], 'response_schema': {'type': 'object'}}
    mod('page_context').attach(q, records, state, run=tmp_path)
    return records, state, q


def test_correction_retains_one_map_and_original_goal_across_refresh(tmp_path):
    _, _, original = mapped_case(tmp_path)
    value = job(); value['request'] = original
    context = {'任务目标': {'控件': 'Add city'}, '失败对象': {'控件': 'Add city'}}
    q = mod('step_repair').request(ROOT, value, context)
    obj = json.loads(q['user_prompt'])
    title = mod('page_context').TITLE
    assert obj[title] == q['_page_context_text']
    assert 'Inspect direct feedback only' in obj['原动态上下文']
    assert q['_page_context_text'] not in obj['原动态上下文']
    assert 'Observed actual result' in obj[title]
    assert q['screenshots'] == original['screenshots']
    before = q['user_prompt']; mod('page_context').refresh(q)
    assert q['user_prompt'] == before
    assert json.loads(before)['相关记录与可用能力'] == context
    q['user_prompt'] += '\nNormal scope suffix'
    mod('page_context').refresh(q)
    assert q['user_prompt'].endswith('\nNormal scope suffix')
    decoded = json.JSONDecoder().raw_decode(q['user_prompt'])[0]
    assert decoded[title] == q['_page_context_text']


def test_handoff_moves_only_when_original_update_confirms_its_content(tmp_path):
    records, state, q = mapped_case(tmp_path)
    action = records['world']['actions']['a1']
    action['evidence']['result_call'] = '0012'
    state['handoff_summary'] = 'Unique task relationship must survive'
    state['observation']['uncertainties'] = ['Still pending']
    reply = {'handoff_summary': state['handoff_summary'], 'uncertainties': ['Still pending']}
    folder = tmp_path/'calls/0012'; folder.mkdir(parents=True)
    (folder/'response.json').write_text(json.dumps(reply))
    target, page = mod('target_observation'), mod('page_context')
    q['user_prompt'] = 'Current task'; q.pop('_page_context_text')
    target.attach_handoff(q, records, state, tmp_path)
    page.attach(q, records, state, run=tmp_path)
    assert q['user_prompt'].count('Unique task relationship must survive') == 1
    assert 'Unique task relationship must survive' in q['_page_context_text']
    assert '未确认事项' in q['_page_context_text']
    assert 'Add city' in q['user_prompt'].split('上步观察交接：')[1].split(page.MARKER)[0]
    before = q['user_prompt']; page.refresh(q); assert q['user_prompt'] == before
    state['handoff_summary'] = 'Independent branch switch with same last action'
    q2 = {'action_ready': True, 'user_prompt': 'Task', 'screenshots': []}
    target.attach_handoff(q2, records, state, tmp_path); page.attach(q2, records, state, run=tmp_path)
    assert state['handoff_summary'] in q2['user_prompt']
    assert state['handoff_summary'] not in q2['_page_context_text']


def test_current_task_has_one_definition_and_other_owner_keeps_name(tmp_path):
    records, state, q = mapped_case(tmp_path)
    records['dialog']['tasks']['inspect'] = deepcopy(records['world']['tasks']['inspect'])
    state['interactive_regions'] = ['world', 'dialog']
    text = mod('region_tasks').render_current(records, state, current_task={'region': 'world', 'name': 'inspect'})
    assert text.count('inspect') == 1  # Other owner's distinct task.
    assert q['user_prompt'].count('inspect') == 1
    assert q['context_evidence']['definition']['reason'] == 'Inspect direct feedback only'
    assert 'single_action' in q['user_prompt'] and '"处理方式": "explore"' in q['user_prompt']


def test_correction_history_references_exact_snapshot_but_keeps_unique_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    records, state, q = mapped_case(tmp_path)
    for region in records.values(): region['description'] = region['name']
    task = records['world']['tasks']['inspect']
    folder = tmp_path/'action_attempts/a1'; folder.mkdir(parents=True)
    receipt = {'exit_code': 0, 'text_delivered': False, 'input_mode': 'replace',
               'description': 'Input target not confirmed', 'executed_steps': [{'action': 'click', 'x': 1, 'reason': 'focus'}]}
    (folder/'receipt.json').write_text(json.dumps(receipt))
    (folder/'proposal.json').write_text(json.dumps({'action': 'input_text', 'text': 'London'}))
    mod('page_context').attach(q, records, state, run=tmp_path)
    value = job(); value['request'] = q
    m = mod('repair_stages'); original = m.helper
    monkeypatch.setattr(m, 'related', lambda *args: {'world': records['world']})
    monkeypatch.setattr(m, 'helper', lambda name: SimpleNamespace(load=lambda run: (tmp_path, records, state)) if name == 'discovery_step' else original(name))
    actual = m.context(tmp_path, value)
    row = actual['区块'][0]['任务'][0]
    assert '共同地图' in str(row['尝试事实']) and 'Observed actual result' not in str(row['尝试事实'])
    assert '说明' not in row and '当前任务' in row['定义']
    assert actual['任务目标']['任务'] == actual['失败对象']['任务'] == '本轮当前任务（定义见原动态上下文）'
    raw = actual['最近尝试原始证据'][0]
    assert raw['提案']['text'] == 'London'
    # Raw receipt details are relevant to this exceptional correction only.
    assert raw['执行回执']['exit_code']==0 and raw['执行回执']['input_mode'] == 'replace'
    assert raw['执行回执']['executed_steps'][0]['reason'] == 'focus'
    task['result_evidence'] = 'New judgment from another snapshot'
    changed = m.context(tmp_path, value)['区块'][0]['任务'][0]
    assert 'New judgment' in str(changed['尝试事实'])
    task.update(status='done', completion_basis={'destination_regions': ['dialog']})
    done = m.context(tmp_path, value)['区块'][0]['任务'][0]
    assert 'Add city dialog' in str(done['尝试事实'])
