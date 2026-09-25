"""Explicit repartition is observation work, not a GUI action or fresh coverage."""
from dataclasses import asdict

import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn, ReportCorrections
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import (
    Page, PageState, Region, RegionVariant, RegionOccurrence, Element, Operation,
    Task, ActionAttempt,
)
from .explore_fixtures import _turn, _known_screen, _png


def coarse_ledger():
    ledger = ExplorationLedger()
    page = Page(ledger.mint('page'), 'Application', 'Two content views')
    ledger.pages[page.page_id] = page
    for index in range(2):
        state = PageState(ledger.mint('state'), page.page_id, f'view {index}', 'content', f'frame{index}.png', survey_complete=True)
        ledger.states[state.state_id] = state
        page.state_ids.append(state.state_id)
        region = Region(ledger.mint('region'), f'coarse view {index}', 'navigation and content')
        ledger.regions[region.region_id] = region
        variant = RegionVariant(ledger.mint('region_variant'), region.region_id)
        ledger.region_variants[variant.variant_id] = variant
        occurrence = RegionOccurrence(ledger.mint('occurrence'), region.region_id, state.state_id, region.name, region.summary, variant.variant_id)
        ledger.occurrences[occurrence.occurrence_id] = occurrence
        state.region_occurrence_ids.append(occurrence.occurrence_id)
        for label in ['navigation menu', f'content {index}']:
            element = Element(ledger.mint('element'), region.region_id, variant.variant_id, label, source_occurrence_ids=[occurrence.occurrence_id])
            ledger.elements[element.element_id] = element
            op = Operation(operation_id=ledger.mint('operation'), region_id=region.region_id, action='click', target=label, status='pending', reason='unknown', source_occurrence_ids=[occurrence.occurrence_id], variant_id=variant.variant_id, element_id=element.element_id)
            ledger.operations[op.operation_id] = op
            ledger.ensure_operation_identity(op.operation_id)
            task = Task(ledger.mint('task'), 'explore_operation', 'pending', state.state_id, op.operation_id, attempt_count=3)
            ledger.tasks[task.task_id] = task
    ledger.current_page_id = 'p1'
    ledger.current_state_id = 's2'
    ledger.current_task_id = 't1'
    ledger.tasks['t1'].status = 'active'
    ledger.attempts['a1'] = ActionAttempt('a1', 't1', 's1', 'route', {'kind': 'back', 'owner_ref': '', 'operation_ref': ''}, 'before.png', outcome='success', target_state_id='s2', after_ref='after.png')
    ledger._rebuild_derived_indexes()
    return ledger


def proposal():
    return {'name': 'Navigation', 'summary': 'Stable navigation distinct from content', 'reason': 'Content changes while these controls persist', 'sources': [
        {'occurrence_ref': 'ro1', 'element_refs': ['el1']},
        {'occurrence_ref': 'ro2', 'element_refs': ['el3']},
    ]}


class Reviewer:
    def __init__(self, approved=True, pair_decision='same'):
        self.approved = approved
        self.pair_decision = pair_decision
        self.roles = []

    def review_region_refinement(self, *, payload, screenshots):
        self.roles.append('region')
        assert len(screenshots) >= 2
        return {'approved': self.approved, 'reason': 'Observed component boundary', 'shared_operations': [
            {'current_operation_ref': 'o3', 'known_operation_ref': 'o1'}
        ] if self.approved else []}

    def review_operation_identities(self, *, payload, screenshots):
        self.roles.append('operation')
        return {'decisions': [{'current_operation_ref': x['current_operation_ref'], 'known_operation_ref': x['known_operation_ref'], 'decision': self.pair_decision, 'reuse_level': 'identity' if self.pair_decision == 'same' else 'none', 'reason': 'Full-frame comparison'} for x in payload['candidate_pairs']], 'reason': 'checked'}


def run_refinement(ledger, reviewer=None, request=None):
    from gui_rewalk.src.core.explore.region_refinement import refine_regions
    return refine_regions(ledger, request or proposal(), agent=reviewer or Reviewer(), current_state_id='s2', screenshot=_png('blue'), screenshot_ref='fresh.png', read_screenshot=lambda ref: _png('red'), corrections=ReportCorrections())


def test_main_parser_preserves_explicit_refinement_tool():
    raw = _turn(screen=_known_screen())
    raw['region_refinement'] = proposal()
    turn = parse_turn(raw, has_pending_action=False)
    assert turn.region_refinement == proposal()


@pytest.mark.parametrize('extra', ['action', 'page_report'])
def test_refinement_cannot_execute_or_inventory_in_same_turn(extra):
    raw = _turn(screen=_known_screen(), action={'kind': 'back', 'owner_ref': '', 'target': 'back'} if extra == 'action' else None, page_report={'regions': [], 'survey_complete': True, 'coverage_note': 'done'} if extra == 'page_report' else None)
    raw['region_refinement'] = proposal()
    with pytest.raises(ValueError, match='region_refinement'):
        parse_turn(raw, has_pending_action=False)


def test_extracts_shared_component_preserving_local_evidence_and_task_budget(tmp_path):
    old = coarse_ledger()
    before = old.snapshot()
    reviewer = Reviewer()
    new = run_refinement(old, reviewer)
    assert old.snapshot() == before
    assert reviewer.roles == ['region', 'operation']
    assert new.elements['el1'].region_id == new.elements['el3'].region_id
    assert new.elements['el2'].region_id == 'r1'
    assert new.elements['el4'].region_id == 'r2'
    assert 'r1' in new.regions and 'r2' in new.regions
    assert new.operations['o1'].canonical_operation_id == new.operations['o3'].canonical_operation_id
    assert new.operation_task('o1') is new.operation_task('o3')
    assert new.operation_task('o1').attempt_count == 6
    assert asdict(new.attempts['a1']) == asdict(old.attempts['a1'])
    assert new.operations['o1'].status != 'verified'
    for sid, parent in [('s1', 'ro1'), ('s2', 'ro2')]:
        child = [o for o in new.state_occurrences(sid) if o.region_id == new.elements['el1'].region_id]
        assert len(child) == 1 and child[0].parent_occurrence_id == parent
    new.validate_region_parentage()
    new.save(tmp_path / 'ledger.json')
    loaded = ExplorationLedger.load(tmp_path / 'ledger.json')
    assert loaded.elements['el1'].region_id == loaded.elements['el3'].region_id
    from gui_rewalk.src.core.explore.status import current_operation_binding
    assert current_operation_binding(loaded, 'o1').element_id == 'el3'


def test_region_refusal_leaves_graph_unchanged_and_skips_operation_review():
    old = coarse_ledger()
    before = old.snapshot()
    reviewer = Reviewer(approved=False)
    with pytest.raises(ValueError, match='refinement'):
        run_refinement(old, reviewer)
    assert old.snapshot() == before and reviewer.roles == ['region']


def test_different_operations_share_component_but_keep_tasks_separate():
    new = run_refinement(coarse_ledger(), Reviewer(pair_decision='different'))
    assert new.elements['el1'].region_id == new.elements['el3'].region_id
    assert new.operation_task('o1') is not new.operation_task('o3')


@pytest.mark.parametrize('mutation', ['foreign', 'duplicate', 'empty', 'pending'])
def test_invalid_refinement_is_rejected_before_model_calls(mutation):
    old, req, reviewer = coarse_ledger(), proposal(), Reviewer()
    if mutation == 'foreign': req['sources'][0]['element_refs'] = ['el3']
    if mutation == 'duplicate': req['sources'][0]['element_refs'] = ['el1', 'el1']
    if mutation == 'empty': req['sources'][0]['element_refs'] = []
    if mutation == 'pending': old.attempts['a1'].outcome = 'pending'
    before = old.snapshot()
    with pytest.raises(ValueError): run_refinement(old, reviewer, req)
    assert reviewer.roles == [] and old.snapshot() == before


def test_shared_canonical_cannot_be_partially_moved():
    old = coarse_ledger()
    old.operations['o2'].canonical_operation_id = old.operations['o1'].canonical_operation_id
    old._rebuild_derived_indexes()
    reviewer = Reviewer()
    with pytest.raises(ValueError, match='all existing shared bindings'):
        run_refinement(old, reviewer)
    assert reviewer.roles == []


def test_refinement_reuses_verified_goal_without_faking_local_success():
    old = coarse_ledger()
    old.operations['o3'].status = 'verified'
    old.tasks['t3'].status = 'done'
    old.tasks['t3'].attempt_count = 2
    new = run_refinement(old)
    from gui_rewalk.src.core.explore.tasks import TaskScheduler
    TaskScheduler().choose(new)
    assert new.operation_task('o1').status == 'done'
    assert new.operation_task('o1').attempt_count == 5
    assert new.operations['o1'].status == 'recorded'
    assert new.operations['o1'].result == ''
    assert new.operations['o3'].status == 'verified'


def test_runtime_dispatches_refinement_without_gui_and_persists_it(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Env
    raw = _turn(screen={**_known_screen(), 'state_ref': 's2'})
    raw['region_refinement'] = proposal()

    class Agent(Reviewer):
        def decide(self, **kwargs):
            return parse_turn(raw, has_pending_action=False)

    agent = Agent()
    env = _Env(_png('blue'), _png('blue'))
    runtime = ExplorationRuntime(env=env, app_name='test', platform='desktop', output_root=str(tmp_path), agent=agent, max_actions=8)
    runtime.ledger = coarse_ledger()
    runtime.max_turns = 1
    (tmp_path / 'frame0.png').write_bytes(_png('red'))
    result = runtime.run(env._get_obs())
    assert result.actions_used == 0 and env.actions == []
    assert runtime.ledger.elements['el1'].region_id == runtime.ledger.elements['el3'].region_id
    assert agent.roles == ['region', 'operation']
    assert runtime.ledger.operation_task('o1').attempt_count == 6
    assert ExplorationLedger.load(tmp_path / 'exploration_ledger.json').elements['el1'].region_id != 'r1'


def test_existing_agent_uses_existing_role_for_refinement():
    from gui_rewalk.src.core.explore.agent import QwenExplorerAgent
    agent = object.__new__(QwenExplorerAgent)
    calls = []
    agent._call = lambda **kwargs: calls.append(kwargs) or {'approved': False, 'reason': 'uncertain', 'shared_operations': []}
    agent.review_region_refinement(payload={'proposal': proposal()}, screenshots=[_png('red')])
    assert calls[0]['role'] == 'modular_region_identity'
    assert 'approved' in calls[0]['response_schema']['required']


def test_shared_operation_candidates_are_injective_within_source():
    class BadReviewer(Reviewer):
        def review_region_refinement(self, **kwargs):
            self.roles.append('region')
            return {'approved': True, 'reason': 'same', 'shared_operations': [
                {'current_operation_ref': 'o3', 'known_operation_ref': 'o1'},
                {'current_operation_ref': 'o4', 'known_operation_ref': 'o1'},
            ]}
    old = coarse_ledger()
    # Add a retained content child so the second source can extract both controls.
    extra = Element(old.mint('element'), 'r2', 'rv2', 'retained content', source_occurrence_ids=['ro2'])
    old.elements[extra.element_id] = extra
    old._rebuild_derived_indexes()
    req = proposal()
    req['sources'][1]['element_refs'].append('el4')
    reviewer = BadReviewer()
    with pytest.raises(ValueError, match='pair'):
        run_refinement(old, reviewer, req)
    assert 'operation' not in reviewer.roles


def test_focus_budget_message_does_not_claim_direct_operation_execution(tmp_path):
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Env
    runtime = ExplorationRuntime(env=_Env(_png('blue'), _png('blue')), app_name='test', platform='desktop', output_root=str(tmp_path), agent=Reviewer(), max_actions=8)
    runtime.ledger = coarse_ledger()
    task = runtime.ledger.tasks['t1']
    task.attempt_count = 12
    assert runtime._fail_exhausted_task(task)
    assert '任务' in task.reason and '导航' in task.reason
    assert '目标操作已执行' not in task.reason
    assert runtime.ledger.operations['o1'].attempt_count == 0


def test_observation_tool_can_omit_redundant_screen_report():
    raw = _turn(screen=None)
    raw['region_refinement'] = proposal()
    turn = parse_turn(raw, has_pending_action=False)
    assert turn.screen is None and turn.region_refinement == proposal()


def test_tool_without_screen_requires_runtime_confirmed_location(tmp_path):
    from dataclasses import replace
    from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
    from .explore_fixtures import _Env
    raw = _turn(screen={**_known_screen(), 'state_ref': 's2'})
    raw['region_refinement'] = proposal()
    turn = replace(parse_turn(raw, has_pending_action=False), screen=None)
    runtime = ExplorationRuntime(env=_Env(_png('blue'), _png('blue')), app_name='test', platform='desktop', output_root=str(tmp_path), agent=Reviewer(), max_actions=8)
    runtime.ledger = coarse_ledger()
    with pytest.raises(ValueError, match='confirmed'):
        runtime._apply_region_refinement(turn, screenshot=_png('blue'), frame_ref='fresh.png')
    runtime.confirmed_state_id = 's2'
    (tmp_path / 'frame0.png').write_bytes(_png('red'))
    runtime._apply_region_refinement(turn, screenshot=_png('blue'), frame_ref='fresh.png')
    assert runtime.ledger.elements['el1'].region_id == runtime.ledger.elements['el3'].region_id


def test_operation_review_names_each_actual_source_state():
    class Capture(Reviewer):
        def review_region_refinement(self, **kwargs):
            return {'approved': True, 'reason': 'same component', 'shared_operations': [
                {'current_operation_ref': 'o1', 'known_operation_ref': 'o3'}]}

        def review_operation_identities(self, *, payload, screenshots):
            pair = payload['candidate_pairs'][0]
            assert pair['current_state'] == 'view 0'
            assert pair['known_state'] == 'view 1'
            assert pair['current_page'] == pair['known_page'] == 'Application'
            return super().review_operation_identities(payload=payload, screenshots=screenshots)
    req = proposal()
    req['sources'].reverse()
    run_refinement(coarse_ledger(), Capture(), req)
