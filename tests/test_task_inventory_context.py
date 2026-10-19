from regrow.records.tasks import coverage as _test_fn_coverage
'Inventory relevance must preserve identity, obligations and evidence roles.'
from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import ROOT, mod
from tests.test_context_relevance import records, task, effort

@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))

def case():
    rs = records()
    r = rs['r1']
    r['controls'] = {cid: {'name': cid, 'observations': [{'icon_description': cid + ' appearance', 'evidence': {'observation': 'old'}}]} for cid in ('visible', 'last', 'goal', 'historical')}
    r['tasks'] = {cid: {**task(), 'control': cid, 'handling': 'explore', 'status': 'done', 'reason': cid + ' OLD_REASON', 'knowledge': cid + ' KNOWLEDGE'} for cid in r['controls']}
    r['tasks']['goal']['status'] = 'pending'
    r['tasks']['Scroll'] = {**task(), 'control': None, 'handling': 'explore', 'status': 'blocked', 'reason': 'unknown below', 'blocker': {'reason': 'need revisit', 'condition': 'review_required'}}
    r['actions'] = {'a9': effort('last', 'open page')}
    state = {'interactive_regions': ['r1'], 'working_region': 'r1', 'observation': {'id': 'now', 'image': 'frame.png', 'control_refs': ['visible']}, 'active_task': {'region': 'r1', 'name': 'goal'}, 'last_action_result': {'region': 'r1', 'action': 'a9'}}
    return (rs, state)

def test_current_candidates_hidden_goal_and_last_target_keep_detail_without_claiming_visibility():
    (rs, state) = case()
    before = deepcopy((rs, state))
    value = mod('task_inventory_context').project(rs, state, 'r1')
    details = {c['control']: c for c in value['控件']}
    assert set(details) == {'visible', 'last', 'goal'}
    assert details['last']['定位依据'] == {'观察来源': 'now', '已定位': False}
    assert details['goal']['定位依据'] == details['last']['定位依据']
    assert details['visible']['定位依据']['观察来源'] == 'now'
    assert details['visible']['定位依据']['已定位'] is True
    assert '本轮已定位' not in json.dumps(value, ensure_ascii=False)
    assert [c['control'] for c in value['历史控件身份索引']] == ['historical']
    assert 'historical KNOWLEDGE' not in json.dumps(value)
    assert {t['name'] for t in value['已有任务']} == set(rs['r1']['tasks'])
    scroll = next((t for t in value['已有任务'] if t['name'] == 'Scroll'))
    assert scroll['reason'] == 'unknown below' and scroll['暂挂原因'] == 'need revisit'
    assert '显式复核' in scroll['恢复条件']
    assert (rs, state) == before

def test_uncovered_identity_is_material_not_a_new_exploration_task():
    (rs, state) = case()
    del rs['r1']['tasks']['historical']
    before = deepcopy((rs, state))
    q = mod('task_proposer').plan_request(ROOT, rs, state, 'r1')
    value = json.loads(q['user_prompt'])
    uncovered = next((c for c in value['控件'] if c['control'] == 'historical'))
    assert uncovered['region'] == 'r1' and uncovered['name'] == 'historical'
    assert '尚无任务覆盖' in uncovered['展开原因']
    assert (rs, state) == before
    assert {t['name'] for key in ('本轮可判断旧任务', '其他任务背景') for t in value[key]} == set(rs['r1']['tasks'])

def test_completed_task_bindings_and_conditional_knowledge_remain_without_old_reasons():
    (rs, state) = case()
    rs['r1']['tasks']['visible']['conditions'] = ['World page']
    q = mod('task_proposer').plan_request(ROOT, rs, state, 'r1')
    value = json.loads(q['user_prompt'])
    t = next((t for t in value['其他任务背景'] if t['name'] == 'visible'))
    assert t['conditions'] == ['World page'] and t['action'] == 'click'
    assert 'reason' not in t
    k = t
    assert k['conditions'] == ['World page'] and k['知识依据']['basis'] == 'explored'
    assert 'attempts' not in k['知识依据'] and 'completion_basis' not in k['知识依据']
    assert value['可引用同类实例'] == []
    new_row = next((branch for branch in q['response_schema']['properties']['operations']['items']['anyOf'] if 'control' in branch['properties']))
    assert set(new_row['properties']['control']['enum']) >= {'historical', 'goal'}

def test_new_sibling_instances_can_share_before_either_is_explored():
    (rs, state) = case()
    for cid in ('London', 'Beijing'):
        rs['r1']['controls'][cid] = {'name': cid, 'observations': [{'evidence': {'observation': 'now'}}]}
    rs['r2']['tasks']['Other'] = {**task(), 'control': 'cr2', 'handling': 'explore', 'status': 'done', 'knowledge': 'shared behavior'}
    q = mod('task_proposer').plan_request(ROOT, rs, state, 'r1')
    value = json.loads(q['user_prompt'])
    local = {c['name']: c for c in value['控件']}
    assert local['London']['region'] == 'r1' and local['Beijing']['control'] == 'Beijing'
    assert all((c['region'] != 'r1' for c in value['可引用同类实例']))
    assert value['可引用同类实例'] == []
    assert 'London' in q['response_schema']['properties']['shared_instances']['items']['properties']['source_control']['enum']

def test_offscreen_local_representative_keeps_one_semantic_basis_for_new_instance():
    (rs, state) = case()
    r = rs['r1']
    r['controls']['new'] = {'name': 'new instance', 'observations': [{'evidence': {'observation': 'now'}}]}
    r['tasks']['historical']['findings'] = {'city': {'description': 'city is an instance parameter', 'domain': {'type': 'text'}, 'conditions': []}}
    value = mod('task_inventory_context').project(rs, state, 'r1')
    row = next((c for c in value['历史控件身份索引'] if c['control'] == 'historical'))
    assert '同类参考知识（历史，非本图状态）' not in row
    stable = next((t for t in value['已有任务'] if t['name'] == 'historical'))
    assert stable['knowledge'] == 'historical KNOWLEDGE'
    assert stable['已知参数']['city']['domain'] == {'type': 'text'}
    assert json.dumps(value).count('historical KNOWLEDGE') == 1
    assert not any((c['region'] == 'r1' for c in value['可引用同类实例']))

def test_inventory_map_references_inventory_knowledge_and_keeps_state(tmp_path):
    from tests.test_current_page_context import case as page_case
    (rs, state, _) = page_case(tmp_path)
    q = {'stage': 'task_proposal', 'source': {'region': state['working_region']}, 'user_prompt': '{}', 'screenshots': [state['observation']['image']]}
    ctx = mod('page_context')
    ctx.attach(q, rs, state, run=tmp_path)
    assert '已完成任务知识' not in q['_page_context_text']
    assert q['_page_context_text'].count('Observed actual result') == 1
    assert q['page_context']['current_tree']
    q['stage'] = 'action_selection'
    q['action_ready'] = True
    ctx.attach(q, rs, state, run=tmp_path)
    assert 'inventory_region' not in q['page_context']

def test_correction_does_not_expand_full_inventory_again(monkeypatch):
    from regrow.traversal import discovery_step as discovery_step
    from regrow.traversal import repair_stages as repair_stages
    from regrow.traversal import step_repair as step_repair
    (rs, state) = case()
    rs['r1']['controls']['historical'].update(description='stored exact description', list_group='old group')
    q = mod('task_proposer').plan_request(ROOT, rs, state, 'r1')
    job = {'stage': 'task_proposal', 'request': q, 'history': [], 'error': 'real diagnosis placeholder'}
    original_helper = repair_stages.helper
    monkeypatch.setattr(discovery_step, 'load', lambda run: (None, rs, state))
    monkeypatch.setattr(repair_stages, 'helper', lambda name: discovery_step if name == 'discovery_step' else original_helper(name))
    value = repair_stages.context('unused', job)
    assert 'OLD_REASON' not in json.dumps(value)
    assert value['区块'][0]['控件可修订原值'][-1] == {'名称': 'historical', 'description': 'stored exact description', 'list_group': 'old group'}
    corrected = step_repair.request(ROOT, job, value)
    assert 'real diagnosis placeholder' in corrected['user_prompt']
    assert 'historical' in corrected['user_prompt'] and 'unknown below' in corrected['user_prompt']

def test_review_material_and_schema_share_the_same_task_scope():
    (rs, state) = case()
    rs['r1']['task_inventory'] = {'review': {'kind': 'entry_observation', 'task': 'goal'}}
    before = deepcopy((rs, state))
    q = mod('task_proposer').plan_request(ROOT, rs, state, 'r1')
    value = json.loads(q['user_prompt'])
    selected = value['本轮可判断旧任务']
    background = value['其他任务背景']
    assert [r['task'] for r in selected] == ['r1/goal']
    allowed = next((b['properties']['task']['enum'] for b in q['response_schema']['properties']['operations']['items']['anyOf'] if 'task' in b['properties']))
    assert allowed == [r['task'] for r in selected]
    assert {r['name'] for r in selected + background} == set(rs['r1']['tasks'])
    assert not {r['task'] for r in selected}.intersection((r['task'] for r in background))
    scroll = next((r for r in background if r['name'] == 'Scroll'))
    assert scroll['暂挂原因'] == 'need revisit' and scroll['conditions'] == []
    text = mod('history_disclosure').project(q)['user_prompt']
    assert text.index('本轮可判断旧任务') < text.index('其他任务背景')
    assert '指定旧问题已有怎样的答案或缺口' in text and 'unknown below' in text
    assert (rs, state) == before

def test_old_uncovered_control_does_not_expand_all_historical_knowledge():
    (rs, state) = case()
    rs['r1']['controls']['old_gap'] = {'name': 'scrollbar', 'observations': []}
    value = mod('task_inventory_context').project(rs, state, 'r1')
    assert 'old_gap' in {c['control'] for c in value['控件']}
    assert 'historical KNOWLEDGE' not in json.dumps(value)
    assert 'historical' in {t['name'] for t in value['已有任务']}

def test_sharing_can_use_current_external_control_but_not_unrelated_history():
    (rs, state) = case()
    rs['r1']['controls']['new'] = {'name': 'new', 'observations': [{'evidence': {'observation': 'now'}}]}
    rs['r2']['tasks']['Other'] = {**task(), 'control': 'cr2', 'handling': 'explore', 'status': 'done', 'knowledge': 'shared behavior'}
    state['interactive_regions'].append('r2')
    state['observation']['control_refs'].append('cr2')
    value = mod('task_inventory_context').project(rs, state, 'r1')
    assert [c['control'] for c in value['可引用同类实例']] == ['cr2']
    assert 'shared behavior' in json.dumps(value)

def test_new_unselected_appearance_reuses_identity_and_does_not_reset_known_task():
    flow = mod('stepwise_flow')
    region = flow.new_region('r0001', 'Navigation')
    region['tasks'] = {}
    region['controls']['c0001'] = {'name': 'A', 'observations': [{'state': 'selected', 'evidence': {'observation': 'before'}}], 'task_refs': ['inspect A']}
    region['tasks']['inspect A'] = {**task(), 'control': 'c0001', 'handling': 'record', 'status': 'record_only', 'knowledge': 'Navigate to A', 'conditions': []}
    region['task_inventory'] = {'inventory': 'complete', 'controls': ['c0001']}
    records = {region['id']: region}
    original = deepcopy(region['tasks'])
    reply = {'regions': [{'name': 'Navigation', 'previous_name': 'Navigation', 'description': 'Navigation after selecting B', 'parent_index': None, 'bbox': None, 'task_review_reason': '', 'reason': 'Same navigation region'}], 'controls': [{'name': 'A', 'previous_name': 'A', 'region_index': 0, 'state': 'unselected', 'icon_appearance': 'Unselected A', 'bbox': None}]}
    mod('register_update').materialize_regions(records, reply, 'after', 'after-B')
    state = {'interactive_regions': ['r0001'], 'observation': {'id': 'after-B', 'control_refs': ['c0001']}}
    mod('task_knowledge').refresh(records, state)
    assert list(region['controls']) == ['c0001']
    assert len(region['controls']['c0001']['observations']) == 2
    assert region['tasks'] == original and (not region['task_inventory'].get('review'))
    assert region['current_observation']['controls']['c0001']['state'] == 'unselected'
    assert 'unselected' not in json.dumps(region['controls']['c0001']['knowledge'])
    reply['controls'] = [{'name': 'B', 'previous_name': '', 'region_index': 0, 'state': 'selected', 'icon_appearance': 'Selected B', 'bbox': None}]
    mod('register_update').materialize_regions(records, reply, 'new', 'new-B')
    assert len(region['controls']) == 2
    assert not _test_fn_coverage(region, records)['inventory_complete']
    assert region['tasks'] == original

def test_pending_discovery_discloses_question_and_provenance_not_old_coordinates():
    from copy import deepcopy
    from regrow.records import task_inventory_context as task_inventory_context
    gap = {'kind': 'control', 'index': 3, 'name': 'item', 'owner': 'panel', 'item': 'panel/item', 'source_call': 'old', 'source_observation': 'discovery:old', 'source_frame': 'old.png', 'proposal': {'name': 'item', 'identity': 'uncertain', 'identity_evidence': 'ambiguous owner', 'uncertainty': 'partially covered', 'image_quality': 'occluded', 'image_quality_reason': 'menu', 'region_index': 0, 'bbox': {'left': 1}, 'click_bbox': None, 'icon_bbox': None}}
    region = {'registration_gaps': {'discovery': {'pending': [gap]}}}
    before = deepcopy(region)
    rows = task_inventory_context.pending_discovery(region)
    assert region == before and rows[0]['source_observation'] == 'discovery:old'
    assert rows[0]['proposal'] == {k: v for (k, v) in gap['proposal'].items() if k not in ('region_index', 'bbox', 'click_bbox', 'icon_bbox')}
    assert 'index' not in rows[0]
