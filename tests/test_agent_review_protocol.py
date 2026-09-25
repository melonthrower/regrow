import json
from copy import deepcopy
from dataclasses import replace

import pytest

from gui_rewalk.src.core.explore.agent import QwenExplorerAgent
from gui_rewalk.src.core.explore.contracts import ReportCorrections, parse_turn, submission_contract
from gui_rewalk.src.core.explore.partition_review import verify_partition
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.settlement import SettlementContractError, resolve_action_operation
from .explore_fixtures import _Agent, _Env, _known_screen, _new_screen, _png, _report, _seed_ledger, _turn
from .test_explore_partition_review import qualification_reply, report


def make_runtime(tmp_path):
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')), app_name='fixture',
        platform='desktop', output_root=str(tmp_path), agent=_Agent([]), max_actions=2,
        execution_scope='允许查看、展开、返回；不提交配置。')
    runtime.ledger = _seed_ledger()
    runtime.confirmed_state_id = 's1'
    runtime.confirmed_screenshot = _png('white')
    return runtime


def test_operation_owner_feedback_uses_graph_not_number_suffix():
    ledger = _seed_ledger()
    operation = ledger.operations.pop('o1')
    operation.operation_id = 'o97'
    ledger.operations['o97'] = operation
    for variant in ledger.region_variants.values():
        variant.operation_ids = ['o97' if ref == 'o1' else ref for ref in variant.operation_ids]
    ledger.elements['el1'].operation_ids = ['o97']
    with pytest.raises(SettlementContractError) as caught:
        resolve_action_operation(ledger, state_id='s1', owner_ref='o97', action='click')
    assert 'type=Operation' in caught.value.received
    assert '候选=el1' in str(caught.value)
    assert 'el97' not in str(caught.value)
    assert '未投递' in str(caught.value)
    with pytest.raises(SettlementContractError) as stale:
        resolve_action_operation(ledger, state_id='missing', owner_ref='o97', action='click')
    assert '候选=el1' not in str(stale.value)


def test_delivery_supersedes_old_action_correction(tmp_path):
    runtime = make_runtime(tmp_path)
    task = runtime.scheduler.choose(runtime.ledger)
    runtime._record_action_rejection(task, 'o4 is Operation; old proposal rejected')
    action = parse_turn(_turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el1', 'target': '开始按钮', 'point_1000': [500, 500]}),
        has_pending_action=False).action
    bound = runtime._bind_action(task, action)
    runtime._execute(task=task, action=bound, screenshot=runtime.confirmed_screenshot)
    context = runtime._context(task, 'target')
    assert runtime.correction == ''
    assert 'o4' not in context['状态栏']
    assert context['待结算动作详情']['attempt_ref'] == 'a1'
    assert context['本轮提交合同']['phase'] == 'settlement'
    assert len(runtime.env.actions) == 1
    assert any(event['kind'] == 'correction_superseded_by_delivery' for event in runtime.ledger.events)


@pytest.mark.parametrize('defect', ['', 'target', 'stale', 'ambiguous', 'rejected'])
def test_unique_confirmation_uses_original_binder_and_dispatch_checks(tmp_path, defect):
    runtime = make_runtime(tmp_path)
    task = runtime.scheduler.choose(runtime.ledger)
    offered = runtime._known_action_candidate(task, runtime.confirmed_screenshot)
    assert offered is not None
    runtime.offered_action_candidate = deepcopy(offered)
    raw = _turn(screen=_known_screen(), action={'kind': offered['kind'], 'target': offered['target'],
        'owner_ref': '@current', 'direction': offered['direction'], 'point_1000': [500, 500]})
    if defect == 'target':
        raw['action']['target'] = 'Another target'
    elif defect == 'stale':
        runtime.confirmed_screenshot = _png('blue')
    elif defect == 'ambiguous':
        duplicate = deepcopy(runtime.ledger.operations[offered['operation_ref']])
        duplicate.operation_id = 'o99'
        runtime.ledger.operations['o99'] = duplicate
        runtime.ledger.elements[duplicate.element_id].operation_ids.append('o99')
    elif defect == 'rejected':
        raw['action'] = None
    turn = parse_turn(raw, has_pending_action=False)
    if defect == 'rejected':
        assert turn.action is None and not runtime.env.actions
    elif defect:
        with pytest.raises(ValueError, match='候选失效|不唯一'):
            runtime._bind_action(task, turn.action)
        assert not runtime.env.actions
    else:
        bound = runtime._bind_action(task, turn.action)
        assert bound.owner_ref == offered['owner_ref'] and bound.operation_ref == offered['operation_ref']
        assert runtime._validate_action(task, bound) == ''
        runtime._execute(task=task, action=bound, screenshot=runtime.confirmed_screenshot)
        assert len(runtime.env.actions) == 1
        assert runtime.ledger.attempts['a1'].action['owner_ref'] == 'el1'


@pytest.mark.parametrize('pending', [False, True])
def test_final_edits_request_and_parser_share_one_contract(tmp_path, pending):
    first = _turn(screen=_new_screen(), page_report=_report())
    if pending:
        first['screen'] = {**_new_screen(), 'identity': 'new_state', 'page_ref': 'p1', 'state_name': 'New foreground'}
        first['previous_action'] = {'attempt_ref': 'a1', 'reason': 'Only inventory correction needed',
            'element_actions': [], 'region_actions': [], 'function_info': [], 'parameter_info': None,
            'region_effects': [], 'representative_same_kind': None}
    invalid = {'app_scope': 'target_app', 'strategy': 'Repair', 'reason': 'Repair',
        'screen': _known_screen(), 'page_report_edits': [{'op': 'remove', 'path': '/regions/0/elements/0'}]}
    patch = {'app_scope': 'target_app', 'strategy': 'Repair', 'reason': 'Repair name only',
        'page_report_edits': [{'op': 'replace', 'path': '/regions/0/elements/0/name', 'value_json': '"Correct control"'}]}
    class Agent(_Agent):
        decide = QwenExplorerAgent.decide
        review_partition = QwenExplorerAgent.review_partition

        def __init__(self):
            super().__init__([])
            self.replies = iter([first, invalid, patch])
            self.requests = []
            self.reviews = 0

        def _call(self, **kwargs):
            self.requests.append(kwargs)
            if kwargs['role'] == 'modular_main_agent':
                return next(self.replies)
            self.reviews += 1
            return {'decision': 'different' if self.reviews == 1 else 'same', 'reason': 'Rename the control'}
    agent = Agent()
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('white')), app_name='fixture',
        platform='desktop', output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.max_turns = 3
    if pending:
        runtime.ledger = _seed_ledger()
        task = runtime.scheduler.choose(runtime.ledger)
        action = runtime._bind_action(task, parse_turn(_turn(screen=_known_screen(), action={
            'kind': 'click', 'owner_ref': 'el1', 'point_1000': [500, 500]}), has_pending_action=False).action)
        runtime._execute(task=task, action=action, screenshot=_png('black'))
    runtime.run(runtime.env._get_obs())
    requests = [request for request in agent.requests if request['role'] == 'modular_main_agent']
    assert len(requests) == 3
    for request in requests[1:]:
        payload = json.loads(request['user_prompt'].split('\n', 1)[1])
        assert payload['本轮提交合同']['phase'] == 'inventory_edits'
        assert payload['推进阶段']['phase'] == 'inventory_edits'
        assert request['response_schema']['properties']['app_scope'] == {'type': 'string', 'enum': ['target_app']}
        for field in ('screen', 'previous_action', 'page_report', 'action'):
            assert request['response_schema']['properties'][field] == {'type': 'null'}
        assert 'screen 必须非空' not in request['user_prompt']
        assert 'screen.identity=uncertain' not in request['user_prompt']
        assert '有 pending 必须原样回填' not in request['system_prompt']
    assert 'screen' in requests[2]['user_prompt'] and '整批编辑未应用' in requests[2]['user_prompt']
    after_format_error = json.loads(requests[2]['user_prompt'].split('\n', 1)[1])
    previous_review = after_format_error['上一轮清单审核']
    assert previous_review['decision'] == 'different'
    assert previous_review['reason'] == 'Rename the control'
    assert previous_review['regions'][0]['path'] == '/regions/0'
    assert previous_review['regions'][0]['name'] == first['page_report']['regions'][0]['name']
    assert any(element.name == 'Correct control' for element in runtime.ledger.elements.values())
    assert len(runtime.env.actions) == int(pending)
    assert not runtime.pending_attempt_id
    assert len([event for event in runtime.ledger.events if event['kind'] == 'page_report_edits_applied']) == 1
    (tmp_path / 'final_requests.json').write_text(json.dumps([
        {key: value for key, value in request.items() if key != 'screenshots'} for request in requests], ensure_ascii=False))


def test_edit_exit_switches_phase_without_fabricating_a_receipt():
    raw = {'app_scope': 'target_app', 'strategy': 'Reobserve', 'reason': 'Cached position needs review'}
    turn = parse_turn(raw, has_pending_action=True, pending_attempt_id='a8',
        submission=submission_contract('a8', edits=True))
    assert turn.previous_action is None and turn.screen is None and turn.action is None
    with pytest.raises(ValueError, match='previous_action'):
        parse_turn(raw, has_pending_action=True, pending_attempt_id='a8')


def test_uncached_inventory_repair_keeps_full_submission_through_settlement(tmp_path):
    from .test_explore_report_commit import _completed, _new_result_screen, _result_report
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el1', 'target': '开始按钮', 'point_1000': [500, 500]})
    rejected = _turn(screen=_new_result_screen(), previous=_completed(),
        page_report=_result_report(invalid=True))
    corrected = _turn(screen=_new_result_screen(), previous=_completed(),
        page_report=_result_report())
    for reply in (rejected, corrected):
        reply['previous_action']['region_effects'] = [
            {'region_ref': '', 'report_index': 0, 'change': 'appeared', 'cause': 'action'}]
    misplaced_edits = {**corrected, 'page_report': None,
        'page_report_edits': [{'op': 'replace', 'path': '/regions/0/region_ref', 'value_json': '""'}]}
    replies = iter([first, execute, rejected, misplaced_edits, corrected])
    requests = []
    class Agent(_Agent):
        decide = QwenExplorerAgent.decide
        def _call(self, **kwargs):
            requests.append(kwargs)
            return next(replies)
    env = _Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=Agent([]), max_actions=1)
    runtime.run(env._get_obs())
    for request in requests[3:]:
        payload = json.loads(request['user_prompt'].split('\n', 1)[1])
        assert payload['本轮提交合同']['phase'] == 'settlement'
        assert '清单增量纠正' not in payload
        assert request['response_schema']['properties']['page_report_edits'] == {'type': 'null'}
    assert 'page_report_edits=null' in requests[4]['user_prompt']
    assert '本轮只提交page_report_edits' not in requests[4]['user_prompt']
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert runtime.pending_attempt_id == '' and len(env.actions) == 1
    assert runtime.ledger.current_state_id == 's2' and runtime.ledger.transitions
    assert not any(event['kind'] == 'page_report_edits_applied' for event in runtime.ledger.events)


@pytest.mark.parametrize('target', ['Apply configuration', 'Commit display selection'])
def test_reason_scope_projection_cache_and_independent_gate(tmp_path, target):
    candidate = report()
    element = candidate.regions[0].elements[0]
    operation = replace(element.operations[0], target=target, handling='defer', reason='Scope forbids committing configuration')
    candidate = replace(candidate, regions=[replace(candidate.regions[0], elements=[replace(element, operations=[operation])])])
    received = []
    class Agent:
        def review_partition(self, **kwargs):
            received.append(kwargs['payload'])
            return {'decision': 'same', 'reason': 'Conservative handling matches scope'}
    cache = {}
    scope = {'goal': 'Observe and return only; no configuration commits'}
    verify_partition(Agent(), report=candidate, screenshot=b'frame', cache=cache, run_scope=scope)
    verify_partition(Agent(), report=candidate, screenshot=b'frame', cache=cache, run_scope=scope)
    assert len(received) == 1
    projected = received[0]['page_report']['regions'][0]['elements'][0]['operations'][0]
    assert projected['reason'] == operation.reason and received[0]['scope'] == scope
    assert not any(field in json.dumps(received) for field in ('bbox', 'point_1000', 'pixel_similarity'))
    verify_partition(Agent(), report=candidate, screenshot=b'frame', cache=cache, run_scope={'goal': 'Different scope'})
    assert len(received) == 2
    runtime = make_runtime(tmp_path)
    task = runtime.scheduler.choose(runtime.ledger)
    action = runtime._bind_action(task, parse_turn(_turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el1', 'point_1000': [500, 500]}), has_pending_action=False).action)
    runtime.scheduler.declare_region('r1', restricted={'co1': 'No configuration commits'})
    assert '受限' in runtime._validate_action(task, action)
    runtime.scheduler.region_declarations.clear()
    runtime.ledger.operations['o1'].status = 'deferred'
    runtime.ledger.operations['o1'].reason = 'Disabled control'
    assert '暂缓' in runtime._validate_action(task, action)
    assert not runtime.env.actions


def test_invalid_reviewer_output_returns_to_same_role_with_shared_budget():
    received = []
    invalid = qualification_reply(eligible=True)
    invalid['operation_checks'][0]['eligible'] = 'yes'
    class Agent:
        def review_partition(self, **kwargs):
            received.append(kwargs['payload'])
            return invalid if len(received) == 1 else qualification_reply(eligible=True)
    budget = ReportCorrections()
    verify_partition(Agent(), report=report(), screenshot=b'frame', cache={}, corrections=budget)
    assert len(received) == 2 and budget.count == 1
    assert received[1]['reviewer_correction']['responsible_role'] == 'partition_reviewer'
    assert received[0]['page_report'] == received[1]['page_report']
    assert budget.events[0]['recipient'] == 'partition_reviewer'
    assert 'boolean' in received[1]['reviewer_correction']['error']


def test_unclassified_error_does_not_invent_previous_action_fix():
    assert ExplorationRuntime._report_error_fields(ValueError('unclassified'))['field_path'] == 'unclassified'


def test_duplicate_physical_controls_repaired_before_visual_review(tmp_path):
    operation = {**_report()['regions'][0]['operations'][0], 'operation_ref': '',
        'direction': '', 'parameter_status': 'none', 'parameter_summary': 'No parameters'}
    first = _turn(screen=_new_screen(), page_report={
        'regions': [{'name': 'Controls', 'summary': 'Two separate controls',
            'elements': [{'name': 'Combined controls', 'element_ref': '',
                'observation': 'Two physical buttons',
                'operations': [operation, {**operation, 'target': 'Menu'}]}]}],
        'survey_complete': True, 'coverage_note': 'Visible controls'})
    fixed = [{'name': name, 'element_ref': '', 'observation': 'Separate physical button',
              'operations': [{**operation, 'target': name, 'handling': 'record'}]}
             for name in ['Main', 'Menu']]
    correction = {'app_scope': 'target_app', 'strategy': 'Repair structure', 'reason': 'Split two physical controls',
        'page_report_edits': [{'op': 'replace', 'path': '/regions/0/elements',
                               'value_json': json.dumps(fixed)}]}
    replies = iter([first, correction]); requests = []; reviews = []
    class Agent(_Agent):
        decide = QwenExplorerAgent.decide
        def _call(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 2:
                assert not reviews and not runtime.ledger.states
                assert 'page_report.regions[0].elements[0].operations' in kwargs['user_prompt']
                assert 'inventory_edits' in kwargs['user_prompt']
            return next(replies)
        def review_partition(self, **kwargs):
            reviews.append(kwargs['payload'])
            assert len(kwargs['payload']['page_report']['regions'][0]['elements']) == 2
            return {'decision': 'same', 'reason': 'Both physical controls now separate'}
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('white')), app_name='fixture',
        platform='desktop', output_root=str(tmp_path), agent=Agent([]), max_actions=1)
    runtime.max_turns = 2
    runtime.run(runtime.env._get_obs())
    assert len(reviews) == 1 and len(runtime.ledger.elements) == 2
    assert not runtime.env.actions
    assert any(e['kind'] == 'page_report_edits_applied' for e in runtime.ledger.events)


def test_empty_inventory_does_not_complete_application(tmp_path):
    raw = _report(); raw['regions'] = []
    frame = _png('white')
    rt = ExplorationRuntime(env=_Env(frame, frame), app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=_Agent([(_turn(screen=_new_screen(), page_report=raw), False)]),
        max_actions=1)
    rt.max_turns = 2
    result = rt.run(rt.env._get_obs())
    assert result.stop_reason == 'foreground_inventory_unconfirmed'
    assert not rt.env.actions


def test_one_physical_control_can_have_distinct_actions_and_parameters():
    from gui_rewalk.src.core.explore.inventory import validate_report_structure
    from dataclasses import asdict
    raw = asdict(parse_turn(_turn(screen=_known_screen(), page_report=_report()), has_pending_action=False).page_report)
    element = raw['regions'][0]['elements'][0]
    click = element['operations'][0]
    element['operations'] = [click, {**click, 'action':'long_press'}]
    validate_report_structure(parse_turn(_turn(screen=_known_screen(), page_report=raw), has_pending_action=False).page_report)
    element['operations'] = [{**click, 'parameter_status':'observed', 'parameter_summary':'choose one of two values'}]
    validate_report_structure(parse_turn(_turn(screen=_known_screen(), page_report=raw), has_pending_action=False).page_report)


def test_uncertain_operation_keeps_gap_and_runs_same_region_sibling(tmp_path):
    from gui_rewalk.src.core.explore.region_work import region_coverage
    inventory = _report()
    inventory['regions'][0]['operations'].append({
        'action': 'click', 'target': '独立查看入口', 'handling': 'explore',
        'reason': '独立查看，不依赖开始按钮执行结果。'})
    first = _turn(screen=_new_screen(), page_report=inventory)
    execute = _turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el1', 'target': '开始按钮', 'point_1000': [300, 500]})
    unknown = _turn(screen=_known_screen(), previous={
        'attempt_ref': 'a1', 'element_actions': [], 'region_actions': [],
        'function_info': [], 'parameter_info': None, 'region_effects': [],
        'reason': '无法确认点击效果，但当前页面及独立入口仍可直接操作。'})
    sibling = _turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el2', 'target': '独立查看入口', 'point_1000': [700, 500]})
    completed = _turn(screen=_known_screen(), previous={
        'attempt_ref': 'a2', 'element_actions': [
            {'element_ref': 'el2', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'parameter_info': None,
        'reason': '独立入口显示预期内容。'})
    class ReviewedAgent(_Agent):
        def review_known_state(self, **kwargs):
            return {'decision': 'same', 'reason': '当前独立控件均可交互。',
                'region_checks': [{'region_ref': r['region_ref'], 'presence': 'present',
                    'current_controls': [e['name'] for e in r['controls']]}
                    for r in kwargs['payload']['historical_regions']]}

    agent = ReviewedAgent([(first, False), (execute, False), (unknown, True),
                    (sibling, False), (completed, True)])
    runtime = ExplorationRuntime(env=_Env(_png('white'), _png('black')),
        app_name='fixture', platform='desktop', output_root=str(tmp_path),
        agent=agent, max_actions=3)
    result = runtime.run(runtime.env._get_obs())
    assert len(runtime.env.actions) == 2
    assert runtime.ledger.attempts['a1'].outcome == 'uncertain'
    assert runtime.ledger.attempts['a2'].outcome == 'success'
    assert runtime.ledger.operation_task('o1').status == 'deferred'
    assert runtime.ledger.operations['o2'].status == 'verified'
    assert agent.contexts[3]['工作区块']['region_ref'] == 'r1'
    assert not region_coverage(runtime.ledger, 'r1')['direct_complete']
    assert result.status == 'partial' and result.gaps
    assert result.stop_reason != 'action_result_unconfirmed'

    assert any(e['kind'] == 'known_state_visually_confirmed' for e in runtime.ledger.events)
    assert not any(t.attempt_id == 'a1' for t in runtime.ledger.transitions)


def test_idle_changed_frame_reobserves_before_ending_without_replaying(tmp_path):
    runtime = make_runtime(tmp_path)
    task = runtime.scheduler.choose(runtime.ledger)
    runtime.scheduler.settle(runtime.ledger, task, result='failed', reason='原操作受阻')
    # New bytes demand fresh observation, not a semantic State change or stop.
    runtime.env.observation = {'screenshot': _png('black')}
    runtime.agent = _Agent([(_turn(screen=_known_screen()), False)])
    result = runtime.run(runtime.env._get_obs())
    assert len(runtime.agent.contexts) == 1
    assert runtime.agent.contexts[0]['推进阶段']['phase'] == 'observe'
    assert result.stop_reason == 'terminal_gaps'
    assert runtime.ledger.operation_task('o1').status == 'failed'
    assert runtime.env.actions == []
    assert any(e['kind'] == 'completion_observation_required' for e in runtime.ledger.events)


def test_idle_reobservation_discovers_control_then_continues(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.scheduler.settle(runtime.ledger, runtime.scheduler.choose(runtime.ledger),
        result='failed', reason='旧入口保留缺口')
    runtime.env.observation = {'screenshot': _png('black')}
    new = _report()
    new['regions'][0]['region_ref'] = 'r1'
    new['regions'][0].pop('operations')
    new['regions'][0]['elements'] = [
        {'element_ref':'el1', 'name':'开始按钮', 'operations':[]},
        {'element_ref':'', 'name':'新发现的独立入口', 'operations':[
            {'action':'click', 'target':'新发现的独立入口', 'handling':'explore',
             'reason':'独立查看入口，无须旧操作成功'}]}]
    runtime.agent = _Agent([
        (_turn(screen=_known_screen(), page_report=new), False),
        (_turn(screen=_known_screen(), action={'kind':'click', 'owner_ref':'el2',
            'target':'新发现的独立入口', 'point_1000':[700,500]}), False),
        (_turn(screen=_known_screen(), previous={'attempt_ref':'a1',
            'element_actions':[{'element_ref':'el2','action':'click','completed':True}],
            'region_actions':[], 'function_info':[], 'parameter_info':None,
            'reason':'新入口实际效果已确认'}), True)])
    result = runtime.run(runtime.env._get_obs())
    assert len(runtime.env.actions) == 1
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert runtime.ledger.operation_task('o1').status == 'failed'
    assert runtime.ledger.operations['o2'].status == 'verified'
    assert result.status == 'partial' and result.gaps


def test_idle_reobservation_uncertain_uses_original_correction_limit(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.scheduler.settle(runtime.ledger, runtime.scheduler.choose(runtime.ledger),
        result='failed', reason='旧入口保留缺口')
    runtime.env.observation = {'screenshot': _png('black')}
    raw = _turn(screen={**_known_screen(), 'identity':'uncertain'})
    runtime.agent = _Agent([(deepcopy(raw), False) for _ in range(3)])
    result = runtime.run(runtime.env._get_obs())
    assert result.stop_reason == 'report_correction_exhausted'
    assert len(runtime.agent.contexts) == 3
    assert not runtime.env.actions
