"""Reject semantic partition defects before publishing a new inventory."""
import pytest
import json
from gui_rewalk.src.core.explore.partition_review import verify_partition
from gui_rewalk.src.core.explore.contracts import parse_turn
from .explore_fixtures import _turn, _known_screen, _report


def report():
    return parse_turn(_turn(screen=_known_screen(),page_report=_report()),has_pending_action=False).page_report


@pytest.mark.parametrize('changed', [True, False])
def test_reviewer_contract_handoff_edits_native_runtime(tmp_path, changed):
    from .explore_fixtures import _Agent, _Env, _png, _new_screen
    from .test_explore_report_commit import _completed, _new_result_screen, _result_report
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    first = _turn(screen=_new_screen(), page_report=_report())
    first['page_report']['regions'].append({
        'name': 'Toolbar', 'summary': 'Child toolbar', 'parent_ref': None, 'region_ref': '', 'memory': '',
        'elements': [], 'region_operations': []})
    edit = {'app_scope': 'target_app', 'strategy': 'Check parent against image',
        'reason': 'Current evidence', 'page_report_edits': [
            {'op': 'replace', 'path': '/regions/1/parent_ref',
             'value_json': '0' if changed else 'null'}]}
    execute = _turn(screen=_known_screen(), action={
        'kind': 'click', 'owner_ref': 'el1', 'target': '开始按钮', 'point_1000': [500, 500]})
    settled = _turn(screen=_new_result_screen(), previous=_completed(), page_report=_result_report())
    settled['previous_action']['region_effects'] = [
        {'region_ref': '', 'report_index': 0, 'change': 'appeared', 'cause': 'action'}]
    replies = iter([first, edit, execute, settled])
    main_inputs, reviews = [], []
    class Agent(_Agent):
        decide = QwenExplorerAgent.decide
        review_partition = QwenExplorerAgent.review_partition
    agent = Agent([])
    def call(**kwargs):
        if kwargs['role'] == 'modular_main_agent':
            main_inputs.append(kwargs['user_prompt'])
            return next(replies)
        payload = json.loads(kwargs['user_prompt'].split('\n', 1)[1])
        reviews.append(payload)
        assert payload['scope']['target_app'] == 'fixture'
        assert payload['scope']['platform'] == 'desktop'
        if len(reviews) <= 2:
            reply = qualification_reply(eligible=True)
            reply.update(decision='different', controls_confirmed=False, operation_checks=[],
                reason='/regions/1/parent_ref may belong to region 0; author must check')
            return reply
        return {'decision': 'same', 'reason': 'Corrected candidate matches current evidence'}
    agent._call = call
    env = _Env(_png('white'), _png('black'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1)
    result = runtime.run(env._get_obs())
    assert 'inventory_edits' in main_inputs[1]
    assert '/regions/1/parent_ref' in main_inputs[1]
    assert '未经确认' in main_inputs[1]
    assert '清单增量纠正' in main_inputs[1]
    assert any(event['kind'] == 'page_report_edits_applied' for event in runtime.ledger.events)
    if changed:
        assert reviews[2]['page_report']['regions'][1]['parent_ref'] == 0
        assert runtime.ledger.attempts['a1'].outcome == 'success'
        assert len(env.actions) == 1
        assert runtime.pending_attempt_id == ''
        assert runtime.ledger.transitions
    else:
        assert len(main_inputs) == 2 and len(reviews) == 2
        assert result.stop_reason == 'report_correction_exhausted'
        assert runtime.report_corrections.count == 3
        assert not env.actions and not runtime.ledger.states


def qualification_reply(*, eligible=False):
    return {'decision': 'same' if eligible else 'different', 'reason': 'Current qualification evidence',
        'protocol': 'partition_qualification.v3', 'foreground_confirmed': True, 'omission_checks': [],
        'partition_confirmed': True, 'controls_confirmed': True, 'blocking_issues': [],
        'operation_checks': [{'path': '/regions/0/elements/0/operations/0',
            'action': 'click', 'field': 'handling', 'eligible': eligible,
            'evidence': 'Control is now enabled' if eligible else 'Availability cannot be confirmed',
            'affected_paths': ['/regions/0/elements/0/operations/0']} ]}


def omission_reply(screenshot=b'frame'):
    import hashlib
    path = '/regions/0/elements/0/operations/0'
    return {**qualification_reply(), 'operation_checks': [], 'omission_checks': [{
        'region_path': '/regions/0', 'image_sha256': hashlib.sha256(screenshot).hexdigest(),
        'box_1000': [100, 100, 250, 200], 'description': 'Independent optional input omitted',
        'evidence': 'Visible optional field in the confirmed foreground container', 'affected_paths': [],
        'independent_operations': [{'path': path, 'dependencies': [],
            'evidence': 'Visible Cancel dismisses this dialog regardless of the optional input'}],
        'exit_path': path, 'exit_evidence': 'Cancel is visible and does not submit this form'}]}


@pytest.mark.parametrize('defect', ['', 'dependency', 'frame', 'region', 'exit', 'unconfirmed', 'old_protocol', 'whole_frame'])
def test_omission_admission_checks_references_and_dependencies(defect):
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    reply = omission_reply()
    omission = reply['omission_checks'][0]
    if defect == 'dependency':
        omission['independent_operations'][0]['dependencies'] = ['/regions/0']
    elif defect == 'frame':
        omission['image_sha256'] = 'old-frame'
    elif defect == 'region':
        omission['region_path'] = '/regions/9'
    elif defect == 'exit':
        omission['exit_path'] = '/regions/0/elements/999/operations/0'
    elif defect == 'unconfirmed':
        reply['foreground_confirmed'] = False
    elif defect == 'old_protocol':
        reply['protocol'] = 'partition_qualification.v1'
    elif defect == 'whole_frame':
        omission['box_1000'] = [0, 0, 1000, 1000]
    class Agent:
        def review_partition(self, **kwargs):
            return reply
    cache = {}
    if defect:
        with pytest.raises(SettlementContractError) as rejected:
            verify_partition(Agent(), report=report(), screenshot=b'frame', cache=cache)
        if defect == 'whole_frame':
            assert 'omission_checks[0].box_1000' in str(rejected.value)
            assert '整屏框' in str(rejected.value)
    else:
        verify_partition(Agent(), report=report(), screenshot=b'frame', cache=cache)
        assert cache['result']['decision'] == 'different'
        assert cache['qualification']['omission_checks']


def test_omission_allows_references_to_trusted_reported_dependencies():
    from dataclasses import replace
    original = report()
    region = original.regions[0]
    extra = replace(region.elements[0], name='Independent prerequisite')
    candidate = replace(original, regions=[replace(region, elements=[*region.elements, extra])])
    reply = omission_reply()
    check = reply['omission_checks'][0]
    path = '/regions/0/elements/1/operations/0'
    check['independent_operations'][0]['dependencies'] = [path]
    check['independent_operations'].append({'path': path, 'dependencies': [],
        'evidence': 'Reported enabled prerequisite does not require omitted input'})
    class Agent:
        def review_partition(self, **kwargs):
            return reply
    cache = {}
    verify_partition(Agent(), report=candidate, screenshot=b'frame', cache=cache)
    assert cache['qualification']['omission_checks']


def test_omission_gap_persists_while_trusted_operation_executes(tmp_path):
    from .explore_fixtures import _Agent, _Env, _png, _seed_ledger
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from gui_rewalk.src.core.explore.region_work import region_coverage
    from gui_rewalk.src.core.explore.tasks import deferred_inventory_reports
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    frame = _png('white')
    class Agent(_Agent):
        def review_partition(self, **kwargs):
            return omission_reply(frame)
    raw = _report()
    raw['regions'][0]['region_ref'] = 'r1'
    previous = {'attempt_ref': 'a1', 'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'region_effects': [], 'parameter_info': None,
        'reason': 'Synthetic trusted direct result'}
    agent = Agent([(_turn(screen=_known_screen(), page_report=raw), False),
        (_turn(screen=_known_screen(), action={'kind': 'click', 'owner_ref': 'el1', 'point_1000': [500, 500]}), False),
        (_turn(screen=_known_screen(), previous=previous), True)])
    runtime = ExplorationRuntime(env=_Env(frame, frame), app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = _seed_ledger()
    runtime.max_turns = 3
    runtime.run(runtime.env._get_obs())
    assert len(runtime.env.actions) == 1
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert len(runtime.ledger.operations) == 1
    assert deferred_inventory_reports(runtime.ledger)['s1']['issue_kind'] == 'independent_omission'
    coverage = region_coverage(runtime.ledger, 'r1')
    assert coverage['verified'] == 1
    assert not coverage['direct_complete']
    assert coverage['missing_operation_count'] is None
    assert runtime.restore(str(tmp_path / 'exploration_ledger.json'))
    assert deferred_inventory_reports(runtime.ledger)['s1']['omissions']
    pending = parse_turn(_turn(screen=_known_screen(), previous=previous),
        has_pending_action=True, pending_attempt_id='a1').previous_action
    with pytest.raises(SettlementContractError, match='漏项'):
        validate_qualification_dependencies(report(), omission_reply(frame), runtime.ledger, pending)


def test_independent_omission_can_coexist_with_unrelated_pending_action():
    from dataclasses import replace
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    original = report()
    first = replace(original.regions[0], elements=[replace(original.regions[0].elements[0], element_ref='el1')])
    second = replace(original.regions[0], region_ref='r2', name='Independent region',
                     elements=[replace(original.regions[0].elements[0], element_ref='el2')])
    candidate = replace(original, regions=[first, second])
    reply = omission_reply()
    omission = reply['omission_checks'][0]
    omission['region_path'] = '/regions/1'
    omission['independent_operations'] = [
        {'path': '/regions/0/elements/0/operations/0', 'dependencies': [],
         'evidence': 'Existing operation does not depend on omitted region'},
        {'path': '/regions/1/elements/0/operations/0', 'dependencies': [],
         'evidence': 'Omitted region is separate from the pending operation'},
    ]
    previous = parse_turn(_turn(screen=_known_screen(), previous={
        'attempt_ref': 'a1', 'element_actions': [{'element_ref': candidate.regions[0].elements[0].element_ref, 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'parameter_info': None,
        'region_effects': [], 'reason': 'Trusted operation in the first region'}),
        has_pending_action=True, pending_attempt_id='a1').previous_action
    validate_qualification_dependencies(candidate, reply, _seed_ledger(), previous)


def test_cross_page_omission_uses_real_source_attempt_not_landing_owner():
    from dataclasses import replace
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    original = report()
    candidate = original
    reply = omission_reply()
    previous = parse_turn(_turn(screen=_known_screen(), previous={
        'attempt_ref': 'a1', 'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'parameter_info': None,
        'region_effects': [], 'reason': 'Archive navigation completed'}),
        has_pending_action=True, pending_attempt_id='a1').previous_action
    from gui_rewalk.src.core.explore.models import ActionAttempt
    ledger = _seed_ledger()
    ledger.attempts['a1'] = ActionAttempt(
        attempt_id='a1', task_id='', source_state_id='s1', purpose='route',
        action={'operation_ref': 'o1', 'kind': 'click'}, before_ref='before.png')
    screen_raw = {**_known_screen(), 'state_ref': 's2', 'state_name': 'Archive contents'}
    screen = parse_turn(_turn(screen=screen_raw), has_pending_action=False).screen
    validate_qualification_dependencies(candidate, reply, ledger, previous, current_screen=screen)


def test_unpublished_new_state_landing_uses_source_effects_without_fake_state_ref():
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from .explore_fixtures import _seed_ledger

    candidate = report()
    reply = omission_reply()
    previous = parse_turn(_turn(screen=_known_screen(), previous={
        'attempt_ref': 'a1',
        'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [],
        'function_info': [],
        'parameter_info': None,
        'region_effects': [
            {'region_ref': 'r1', 'change': 'disappeared', 'cause': 'action'},
            {'region_ref': '', 'change': 'appeared', 'cause': 'action'},
        ],
        'reason': 'The source folder was replaced by a new directory listing.',
    }), has_pending_action=True, pending_attempt_id='a1').previous_action
    ledger = _seed_ledger()
    ledger.attempts['a1'] = ActionAttempt(
        attempt_id='a1', task_id='', source_state_id='s1', purpose='route',
        action={'operation_ref': 'o1', 'kind': 'click'}, before_ref='before.png')
    screen = parse_turn(_turn(screen={
        **_known_screen(),
        'identity': 'new_state',
        'page_ref': 'p1',
        'state_ref': '',
        'state_name': 'New directory listing',
        'state_summary': 'The source directory was replaced by a new listing.',
    }), has_pending_action=False).screen

    validate_qualification_dependencies(candidate, reply, ledger, previous, current_screen=screen)


def test_independent_qualification_dispute_preserves_original_verdict():
    class Agent:
        def review_partition(self, **kwargs):
            return qualification_reply()
    cache = {}
    verify_partition(Agent(), report=report(), screenshot=b'frame', cache=cache)
    assert cache['result']['decision'] == 'different'
    assert cache['qualification']['operation_checks'][0]['eligible'] is False


@pytest.mark.parametrize('resolve_gap', [True, False])
def test_partial_region_survives_restore_and_revisits_on_new_route(tmp_path, resolve_gap):
    from copy import deepcopy
    from .explore_fixtures import _Agent, _Env, _png, _new_screen
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from gui_rewalk.src.core.explore.location import bind_screen
    from gui_rewalk.src.core.explore.inventory import apply_page_report
    from gui_rewalk.src.core.explore.ledger import ExplorationLedger
    from gui_rewalk.src.core.explore.region_work import region_coverage
    from gui_rewalk.src.core.explore.partition_review import qualification_gaps
    from gui_rewalk.src.core.explore.status import current_operation_binding

    def inventory(name, targets):
        return {'regions': [{'name': name, 'summary': name, 'operations': [
            {'action': 'click', 'target': target, 'handling': 'record' if target == 'GoS' else 'explore',
             'reason': 'Synthetic independent operation'} for target in targets]}],
            'survey_complete': True, 'coverage_note': 'Declared synthetic controls'}

    ledger = ExplorationLedger()
    screen_r = {**_new_screen(), 'page_name': 'Fixture', 'state_name': 'R'}
    location = bind_screen(ledger, parse_turn(_turn(screen=screen_r), has_pending_action=False).screen, screenshot_ref='')
    ledger = location.ledger
    state_r = location.state_id
    screen_s = {**screen_r, 'identity': 'new_state', 'page_ref': location.page_id, 'state_name': 'S'}
    location = bind_screen(ledger, parse_turn(_turn(screen=screen_s), has_pending_action=False).screen, screenshot_ref='')
    ledger = location.ledger
    state_s = location.state_id
    report_s = parse_turn(_turn(screen=screen_s, page_report=inventory('S', ['D', 'E'])), has_pending_action=False).page_report
    ledger = apply_page_report(ledger, state_id=state_s, report=report_s).ledger
    ledger.current_state_id = state_r
    ledger.current_page_id = location.page_id

    class Environment(_Env):
        state = state_r
        enabled = False
        delivered = []

        def step(self, action, pause=0):
            pending = next(reversed(runtime.ledger.attempts.values()))
            target = runtime.ledger.operations[pending.action['operation_ref']].target
            self.delivered.append(target)
            assert target != 'C' or self.enabled
            if target == 'GoS':
                self.state = state_s
            elif target == 'D':
                self.state = state_r
                self.enabled = True
            self.after = _png('gray' if self.state == state_s else 'white')
            return super().step(action, pause)

    class Agent(_Agent):
        initial = True

        def review_partition(self, **kwargs):
            proposal = kwargs['payload']['page_report']
            reply = {**qualification_reply(), 'decision': 'same', 'operation_checks': []}
            for region_index, region in enumerate(proposal['regions']):
                for element_index, element in enumerate(region['elements']):
                    if element['name'] == 'C':
                        path = f'/regions/{region_index}/elements/{element_index}/operations/0'
                        eligible = env.enabled and resolve_gap
                        reply.update(decision='same' if eligible else 'different', operation_checks=[{
                            **qualification_reply(eligible=eligible)['operation_checks'][0],
                            'path': path, 'affected_paths': [path]}])
            return reply

        def decide(self, **kwargs):
            self.contexts.append(kwargs['context'])
            current = runtime.ledger
            screen = {**_known_screen(), 'page_ref': current.current_page_id or 'p1', 'state_ref': env.state}
            previous = None
            if runtime.pending_attempt_id:
                attempt = current.attempts[runtime.pending_attempt_id]
                operation = current.operations[attempt.action['operation_ref']]
                changed = env.state != attempt.source_state_id
                previous = {'attempt_ref': attempt.attempt_id,
                    'element_actions': [{'element_ref': operation.element_id, 'action': 'click', 'completed': True}],
                    'region_actions': [], 'function_info': [], 'parameter_info': None,
                    'region_effects': ([{'region_ref': current.state_occurrences(env.state)[0].region_id,
                        'change': 'appeared', 'cause': 'action'}] if changed else []),
                    'reason': 'Synthetic operation and landing confirmed'}
                return parse_turn(_turn(screen=screen, previous=previous), has_pending_action=True,
                    pending_attempt_id=attempt.attempt_id)
            if self.initial:
                self.initial = False
                return parse_turn(_turn(screen=screen, page_report=inventory('R', ['A', 'B', 'C', 'GoS'])), has_pending_action=False)
            task = current.current_task()
            operation = current.operations.get(task.operation_id) if task else None
            if runtime.resume_region_rediscovery_required or operation and operation.target == 'C' and env.state == state_r:
                regions = []
                for occurrence in current.state_occurrences(env.state):
                    elements = []
                    for element in current.variant_elements(occurrence.variant_id):
                        elements.append({'element_ref': element.element_id, 'name': element.name, 'operations': [
                            {'operation_ref': local.canonical_operation_id, 'action': local.action, 'target': local.target,
                             'handling': 'record' if local.target == 'GoS' else 'explore', 'reason': 'Fresh qualification observation'}
                            for local in current.element_operations(element.element_id)]})
                    regions.append({'region_ref': occurrence.region_id, 'name': occurrence.name, 'summary': occurrence.summary,
                        'elements': elements, 'region_operations': []})
                if runtime.resume_region_rediscovery_required or qualification_gaps(current):
                    return parse_turn(_turn(screen=screen, page_report={'regions': regions, 'survey_complete': True,
                        'coverage_note': 'Fresh synthetic current qualification'}), has_pending_action=False)
            phase = runtime._progress_phase(task)
            route = phase.get('route', {})
            if phase['phase'] == 'navigate':
                step = phase.get('next_step') or route['steps'][0]
                chosen = current.operations[step['operation_ref']]
            elif operation and operation.region_id not in {item.region_id for item in current.state_occurrences(env.state)}:
                chosen = next(local for local in current.operations.values() if local.target == 'GoS')
            else:
                chosen = operation
            assert chosen is not None
            return parse_turn(_turn(screen=screen, action={'kind': 'click', 'owner_ref': chosen.element_id,
                'target': chosen.target, 'point_1000': [500, 500]}), has_pending_action=False)

    env = Environment(_png('white'), _png('white'))
    agent = Agent([])
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop', output_root=str(tmp_path), agent=agent, max_actions=6)
    runtime.ledger = ledger
    runtime.max_turns = 1
    runtime.run(env._get_obs())
    initial_operations = {operation.target: operation for operation in runtime.ledger.operations.values()}
    region_r = initial_operations['A'].region_id
    declaration = [initial_operations[target].canonical_operation_id for target in ['A', 'B', 'C']]
    runtime.scheduler.declare_region(region_r, operations=declaration)
    disputed = initial_operations['C']
    from gui_rewalk.src.core.explore.contracts import ActionRequest
    assert runtime._validate_action(None, ActionRequest(kind='click', purpose='execute',
        operation_ref=disputed.operation_id, owner_ref=disputed.element_id, target='C',
        point_1000=[500, 500], text='', direction='', amount=650))
    with pytest.raises(ValueError, match='资格'):
        runtime.scheduler.select_visible_operation(runtime.ledger, disputed.canonical_operation_id, 'Cannot bypass')
    from gui_rewalk.src.core.explore.knowledge_retrieval import retrieve_controls
    cards = retrieve_controls(runtime.ledger, {'label': 'C'}, limit=20)
    assert any(card.get('executable') is False for card in cards if card['local_operation_ref'] == disputed.operation_id)
    from gui_rewalk.src.core.explore.partition_review import wake_qualification_revisits
    wake_qualification_revisits(runtime.ledger)
    assert runtime.ledger.operation_task(disputed.operation_id).status == 'deferred'
    import json
    scope_path = tmp_path / 'declared_scope.json'
    scope_path.write_text(json.dumps(runtime.scheduler.region_declarations))
    runtime.max_turns = 24
    runtime.run(env._get_obs())
    operations = {operation.target: operation for operation in runtime.ledger.operations.values()}
    assert env.delivered == ['A', 'B', 'GoS', 'D', 'GoS', 'E']
    region_r = operations['A'].region_id
    declaration = [operations[target].canonical_operation_id for target in ['A', 'B', 'C']]
    coverage = region_coverage(runtime.ledger, region_r, {'operations': declaration})
    assert coverage['verified'] == 2 and coverage['in_scope'] == 3 and not coverage['direct_complete']
    isolated_ref = operations['C'].operation_id
    assert isolated_ref in qualification_gaps(runtime.ledger)
    assert operations['C'].attempt_count == 0
    successful = {ref: deepcopy(attempt) for ref, attempt in runtime.ledger.attempts.items() if attempt.outcome == 'success'}
    runtime.artifacts.checkpoint(runtime.ledger)
    restored = ExplorationRuntime(env=env, app_name='fixture', platform='desktop', output_root=str(tmp_path), agent=agent, max_actions=8)
    assert restored.restore(str(restored.artifacts.root / 'exploration_ledger.json'))
    restored.scheduler.declare_region(region_r, **json.loads(scope_path.read_text())[region_r])
    runtime = restored
    assert isolated_ref in qualification_gaps(runtime.ledger)
    assert current_operation_binding(runtime.ledger, isolated_ref) is None
    runtime.max_turns = 18
    runtime.run(env._get_obs())
    assert env.delivered[-2:] == (['D', 'C'] if resolve_gap else ['E', 'D'])
    assert bool(qualification_gaps(runtime.ledger)) is not resolve_gap
    assert region_coverage(runtime.ledger, region_r, {'operations': declaration})['verified'] == (3 if resolve_gap else 2)
    if not resolve_gap:
        assert runtime.ledger.operations[isolated_ref].attempt_count == 0
        assert runtime.ledger.operation_task(isolated_ref).status == 'deferred'
    assert all(runtime.ledger.attempts[ref] == attempt for ref, attempt in successful.items())
    assert any(event['kind'] == 'qualification_revisit_requested' for event in runtime.ledger.events)


@pytest.mark.parametrize('change', [
    {'foreground_confirmed': False}, {'blocking_issues': ['Ownership conflict']},
    {'protocol': 'old'}, {'operation_checks': []},
])
def test_partial_admission_keeps_necessary_evidence_gate(change):
    class Agent:
        def review_partition(self, **kwargs):
            return {**qualification_reply(), **change}
    with pytest.raises(ValueError):
        verify_partition(Agent(), report=report(), screenshot=b'frame', cache={})


@pytest.mark.parametrize('change', [
    {'path': '/regions/0/elements/999/operations/0'},
    {'action': 'input_text'}, {'field': 'identity'},
    {'affected_paths': ['/regions/0/elements/0/operations/0', '/screen']},
])
def test_invalid_qualification_paths_and_dependencies_are_blocked(change):
    class Agent:
        def review_partition(self, **kwargs):
            result = qualification_reply()
            result['operation_checks'][0].update(change)
            return result
    with pytest.raises(ValueError):
        verify_partition(Agent(), report=report(), screenshot=b'frame', cache={})


def test_qualification_cache_does_not_follow_changed_candidate_or_frame():
    from dataclasses import replace
    class Agent:
        calls = 0
        def review_partition(self, **kwargs):
            self.calls += 1
            return qualification_reply() if self.calls == 1 else {'decision': 'different', 'reason': 'No fresh evidence'}
    agent = Agent()
    cache = {}
    verify_partition(agent, report=report(), screenshot=b'frame', cache=cache)
    with pytest.raises(ValueError):
        verify_partition(agent, report=replace(report(), regions=[]), screenshot=b'frame', cache=cache, force=True)
    assert not cache.get('qualification')
    with pytest.raises(ValueError):
        verify_partition(agent, report=report(), screenshot=b'new', cache=cache)


def test_disputed_pending_operation_cannot_use_partial_admission():
    from dataclasses import replace
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    candidate = report()
    candidate = replace(candidate, regions=[replace(candidate.regions[0],
        elements=[replace(candidate.regions[0].elements[0], element_ref='el1')])])
    previous = parse_turn(_turn(screen=_known_screen(), previous={
        'attempt_ref': 'a1', 'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'parameter_info': None, 'reason': 'Cannot trust disputed operation'}),
        has_pending_action=True, pending_attempt_id='a1').previous_action
    with pytest.raises(ValueError, match='争议操作'):
        validate_qualification_dependencies(candidate, qualification_reply(), _seed_ledger(), previous)


def test_saved_calc_contradictory_receipt_stays_uncertain(tmp_path):
    import json
    from pathlib import Path
    from .explore_fixtures import _Agent, _Env
    from gui_rewalk.src.core.explore.ledger import ExplorationLedger
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    source = Path('artifacts/autonomous_flow_20260917_01/calc/calls/0011')
    if not source.exists():
        pytest.skip('Saved Calc evidence not available')
    frames = sorted(source.glob('input_*.png'))
    before, after = frames[0].read_bytes(), frames[-1].read_bytes()
    runtime = ExplorationRuntime(env=_Env(before, after), app_name='fixture', platform='desktop',
        output_root=str(tmp_path), agent=_Agent([]), max_actions=1)
    runtime.ledger = ExplorationLedger.load(source / 'ledger_before.json')
    runtime.pending_attempt_id = 'a2'
    runtime.pending_before = before
    turn = parse_turn(json.loads((source / 'response.json').read_text()),
        has_pending_action=True, pending_attempt_id='a2')
    runtime._settle_pending(turn, screenshot=after, frame_ref='after.png')
    assert runtime.ledger.attempts['a2'].outcome == 'uncertain'
    assert runtime.report_correction_stop_reason == 'action_result_unconfirmed'
    assert not runtime.env.actions


def test_new_landing_can_settle_parent_while_child_qualification_isolated(tmp_path):
    from .explore_fixtures import _Agent, _Env, _png, _seed_ledger
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from gui_rewalk.src.core.explore.partition_review import qualification_gaps
    screen = {**_known_screen(), 'identity': 'new_state', 'state_ref': '',
        'state_name': 'Independent child dialog', 'state_summary': 'New child controls'}
    child_report = _report()
    child_report['regions'][0]['name'] = 'Independent child'
    reply = _turn(screen=screen, page_report=child_report, previous={
        'attempt_ref': 'a1', 'element_actions': [{'element_ref': 'el1', 'action': 'click', 'completed': True}],
        'region_actions': [], 'function_info': [], 'parameter_info': None,
        'region_effects': [{'report_index': 0, 'change': 'appeared', 'cause': 'action'}],
        'reason': 'Parent opened child dialog; child operation was not executed'})
    class Agent(_Agent):
        def review_partition(self, **kwargs):
            return qualification_reply()
    env = _Env(_png('gray'), _png('gray'))
    runtime = ExplorationRuntime(env=env, app_name='fixture', platform='desktop', output_root=str(tmp_path),
        agent=Agent([(reply, True)]), max_actions=1)
    runtime.ledger = _seed_ledger()
    task = runtime.scheduler.choose(runtime.ledger)
    runtime.ledger.attempts['a1'] = ActionAttempt('a1', task.task_id, 's1', 'execute',
        {'kind': 'click', 'operation_ref': 'o1', 'owner_ref': 'el1'}, 'before.png')
    runtime.pending_attempt_id = 'a1'
    runtime.pending_before = _png('white')
    runtime.actions_used = 1
    runtime.max_turns = 1
    runtime.run(env._get_obs())
    assert runtime.ledger.attempts['a1'].outcome == 'success'
    assert runtime.ledger.current_state_id != 's1'
    assert runtime.ledger.operations['o1'].status == 'verified'
    gaps = qualification_gaps(runtime.ledger)
    assert len(gaps) == 1 and 'o1' not in gaps
    assert all(runtime.ledger.operations[ref].status == 'deferred' for ref in gaps)
    assert not env.actions


class Reviewer:
    def __init__(self,decision):self.decision=decision;self.calls=[]
    def review_partition(self,**kwargs):
        self.calls.append(kwargs)
        return {'decision':self.decision,'reason':'A collection was represented as one physical control'}


def test_rejected_partition_returns_concrete_feedback_and_caches_verdict():
    reviewer=Reviewer('different');cache={}
    for _ in range(2):
        with pytest.raises(ValueError,match='page_report') as error:
            verify_partition(reviewer,report=report(),screenshot=b'frame',cache=cache)
        assert 'physical control' in str(error.value)
    assert len(reviewer.calls)==1


def test_accepted_partition_requires_no_repeat_review_for_identical_proposal():
    reviewer=Reviewer('same');cache={}
    verify_partition(reviewer,report=report(),screenshot=b'frame',cache=cache)
    verify_partition(reviewer,report=report(),screenshot=b'frame',cache=cache)
    assert len(reviewer.calls)==1
    verify_partition(reviewer,report=report(),screenshot=b'new frame',cache=cache)
    assert len(reviewer.calls)==2


def test_region_only_confirmation_is_not_a_new_partition():
    from dataclasses import replace
    r=report();r=replace(r,regions=[replace(r.regions[0],region_ref='r1',elements=[],region_operations=[])])
    reviewer=Reviewer('different')
    verify_partition(reviewer,report=r,screenshot=b'frame',cache={})
    verify_partition(reviewer,report=None,screenshot=b'frame',cache={})
    assert not reviewer.calls


def test_runtime_checks_new_partition_before_creating_state(tmp_path):
    from .explore_fixtures import _Agent,_Env,_png,_new_screen
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    class Agent(_Agent):
        def review_partition(self,**kwargs):
            return {'decision':'different','reason':'Background control in foreground inventory'}
    env=_Env(_png('white'),_png('white'))
    agent=Agent([(_turn(screen=_new_screen(),page_report=_report()),False)])
    runtime=ExplorationRuntime(env=env,app_name='sample',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.max_turns=1
    runtime.run(env._get_obs())
    assert not runtime.ledger.states
    assert not runtime.ledger.regions
    assert not env.actions
    assert any(e['kind']=='partition_visual_review_rejected' for e in runtime.ledger.events)


def test_partition_correction_cannot_regress_same_frame_location(tmp_path):
    from dataclasses import replace
    from .explore_fixtures import _Agent,_Env,_png,_new_screen
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    first=_turn(screen=_new_screen(),page_report=_report())
    second=_turn(screen={**_known_screen(),'page_ref':'p404','state_ref':'s404'},page_report=_report())
    second['page_report']['regions'][0]['elements'][0]['name']='Corrected concrete control'
    class Agent(_Agent):
        checks=0
        def review_partition(self,**kwargs):
            self.checks+=1
            return {'decision':'different' if self.checks==1 else 'same','reason':'Partition correction'}
    agent=Agent([(first,False),(second,False)])
    env=_Env(_png('white'),_png('white'))
    runtime=ExplorationRuntime(env=env,app_name='sample',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.max_turns=2
    runtime.run(env._get_obs())
    assert runtime.ledger.current_state_id=='s1'
    assert runtime.ledger.pages['p1'].name=='Stopwatch'
    assert not env.actions
    assert '保留的合法位置提议' in agent.contexts[1]
    assert any(e['kind']=='partition_correction_screen_retained' for e in runtime.ledger.events)


@pytest.mark.parametrize('attempt,frame',[('a2',b'old'),('a1',b'new')])
def test_retained_location_does_not_cross_attempt_or_frame(attempt,frame):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    runtime=object.__new__(ExplorationRuntime)
    runtime.pending_attempt_id=attempt
    runtime.retained_partition_screen=('a1',b'old',object())
    assert runtime._partition_screen_for_frame(frame) is None
    assert runtime.retained_partition_screen is None


def test_parser_failure_also_retains_legal_location_for_runtime_correction(tmp_path):
    from .explore_fixtures import _Env,_png,_new_screen
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    first=_turn(screen=_new_screen(),page_report=_report())
    first['page_report']['regions'][0]['elements'][0]['operations']=[]
    second={'app_scope': 'target_app', 'strategy': 'Repair the missing action', 'reason': 'Observed action retained',
            'page_report_edits': [{'op': 'replace', 'path': '/regions/0/elements/0/operations',
                'value_json': json.dumps(_turn(screen=_new_screen(), page_report=_report())['page_report']['regions'][0]['elements'][0]['operations'])}]}
    replies=iter([first,second]);main_inputs=[]
    agent=object.__new__(QwenExplorerAgent)
    def call(**kwargs):
        if kwargs['role']=='modular_main_agent':
            main_inputs.append(kwargs['user_prompt'])
            return next(replies)
        return {'decision':'same','reason':'Valid concrete inventory'}
    agent._call=call
    env=_Env(_png('white'),_png('white'))
    runtime=ExplorationRuntime(env=env,app_name='sample',platform='desktop',output_root=str(tmp_path),agent=agent,max_actions=1)
    runtime.max_turns=2
    runtime.run(env._get_obs())
    assert runtime.ledger.current_state_id=='s1'
    assert '保留的合法位置提议' in main_inputs[1]
    assert not env.actions


def test_repair_candidate_cannot_skip_review_by_removing_new_controls():
    from dataclasses import replace
    original=report()
    reduced=replace(original,regions=[replace(original.regions[0],region_ref='r1',elements=[],region_operations=[])])
    reviewer=Reviewer('different')
    with pytest.raises(ValueError,match='page_report'):
        verify_partition(reviewer,report=reduced,screenshot=b'frame',cache={},force=True)
    assert len(reviewer.calls)==1


def test_ownerless_back_omission_requires_real_navigation_effects():
    from dataclasses import replace
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from gui_rewalk.src.core.explore.partition_review import validate_qualification_dependencies
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    ledger = _seed_ledger()
    ledger.states['s2'] = replace(ledger.states['s1'], state_id='s2', region_occurrence_ids=['menu_occurrence'])
    # The source contains a menu that the confirmed target no longer contains.
    occurrence = next(iter(ledger.occurrences.values()))
    ledger.occurrences['menu_occurrence'] = replace(occurrence,
        occurrence_id='menu_occurrence', state_id='s2', region_id='menu')
    ledger.attempts['a1'] = ActionAttempt(attempt_id='a1', task_id='',
        source_state_id='s2', purpose='route', action={'kind':'back', 'operation_ref':''},
        before_ref='before.png', after_ref='after.png')
    previous = parse_turn(_turn(screen=_known_screen(), previous={
        'attempt_ref':'a1', 'element_actions':[], 'region_actions':[],
        'function_info':[], 'parameter_info':None,
        'region_effects':[{'region_ref':'menu', 'change':'disappeared', 'cause':'action'}],
        'reason':'Menu closed; target foreground confirmed'}),
        has_pending_action=True, pending_attempt_id='a1').previous_action
    screen = parse_turn(_turn(screen=_known_screen()), has_pending_action=False).screen
    validate_qualification_dependencies(report(), omission_reply(), ledger, previous, current_screen=screen)
    with pytest.raises(SettlementContractError, match='漏项'):
        validate_qualification_dependencies(report(), omission_reply(), ledger,
            replace(previous, region_effects=[]), current_screen=screen)
    with pytest.raises(SettlementContractError, match='漏项'):
        validate_qualification_dependencies(report(), omission_reply(), ledger,
            replace(previous, region_effects=[{'region_ref':'r1','change':'updated','cause':'action'}]),
            current_screen=screen)


def test_contradictory_controls_flag_returns_to_reviewer_before_legal_rejection():
    from copy import deepcopy
    from gui_rewalk.src.core.explore.contracts import ReportCorrections
    from gui_rewalk.src.core.explore.settlement import SettlementContractError
    contradictory = omission_reply()
    contradictory['controls_confirmed'] = False
    received = []
    class Reviewer:
        def review_partition(self, **kwargs):
            received.append(kwargs['payload'])
            if len(received) == 1:
                return deepcopy(contradictory)
            return {**contradictory, 'omission_checks':[], 'operation_checks':[],
                'blocking_issues':['/regions/0/elements/0 combines separate physical controls'],
                'reason':'/regions/0/elements/0 must split separate controls'}
    corrections = ReportCorrections()
    with pytest.raises(SettlementContractError) as rejected:
        verify_partition(Reviewer(), report=report(), screenshot=b'frame', cache={}, corrections=corrections)
    assert len(received) == 2
    assert received[1]['reviewer_correction']['responsible_role'] == 'partition_reviewer'
    assert 'controls_confirmed' in received[1]['reviewer_correction']['error']
    assert rejected.value.code == 'PARTITION_VISUAL_UNCONFIRMED'
    assert 'separate controls' in str(rejected.value)
    assert contradictory['controls_confirmed'] is False and contradictory['omission_checks']


def test_region_scroll_check_reports_specific_reviewer_field_without_changing_author():
    from gui_rewalk.src.core.explore.contracts import ReportCorrections, HANDLING_GUIDANCE
    from copy import deepcopy
    original = report()
    invalid = qualification_reply()
    invalid['operation_checks'][0].update(path='/regions/0/region_operations/0', action='scroll',
        affected_paths=['/regions/0/region_operations/0'])
    calls = []
    class Reviewer:
        def review_partition(self, **kwargs):
            calls.append(kwargs['payload'])
            if len(calls) == 1:
                return deepcopy(invalid)
            return {**qualification_reply(), 'decision':'same', 'operation_checks':[], 'omission_checks':[]}
    cache = {}; corrections = ReportCorrections()
    verify_partition(Reviewer(), report=original, screenshot=b'frame', cache=cache, corrections=corrections)
    assert len(calls) == 2 and corrections.count == 1
    assert 'operation_checks[0].path' in calls[1]['reviewer_correction']['error']
    assert 'scroll' in calls[1]['reviewer_correction']['error']
    assert calls[0]['page_report'] == calls[1]['page_report']
    assert cache['qualification']['decision'] == 'same'
    assert 'survey_complete=false' in HANDLING_GUIDANCE
