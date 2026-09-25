from dataclasses import replace
from copy import deepcopy
import pytest

from gui_rewalk.src.core.explore.models import CanonicalOperation, Element, Operation, Region, RegionOccurrence, RegionVariant, Task
from gui_rewalk.src.core.explore.tasks import TaskScheduler
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from .explore_fixtures import _seed_ledger, _Env, _Agent, _png


def two_regions():
    ledger=_seed_ledger()
    ledger.regions['r2']=Region('r2','Working region','Two direct controls',
        operation_ids=['b1','b2'],occurrence_ids=['rb'],variant_ids=['vb'],
        canonical_operation_ids=['cb1','cb2'],element_ids=['eb1','eb2'])
    ledger.occurrences['rb']=RegionOccurrence('rb','r2','s1','Working region','',variant_id='vb')
    ledger.states['s1'].region_occurrence_ids.append('rb')
    ledger.region_variants['vb']=RegionVariant('vb','r2',['rb'],['b1','b2'],['eb1','eb2'])
    for i in [1,2]:
        ledger.elements[f'eb{i}']=Element(f'eb{i}','r2','vb',f'Control {i}',[f'b{i}'],['rb'])
        ledger.operations[f'b{i}']=Operation(f'b{i}','r2','click',f'Control {i}','pending',
            source_occurrence_ids=['rb'],variant_id='vb',canonical_operation_id=f'cb{i}',element_id=f'eb{i}',parameter_status='none')
        ledger.canonical_operations[f'cb{i}']=CanonicalOperation(f'cb{i}','r2','click',f'Control {i}',[f'b{i}'])
        ledger.tasks[f'tb{i}']=Task(f'tb{i}','explore_operation','pending','s1',f'b{i}',created_seq=100+i)
    ledger.tasks['tb1'].status='active';ledger.current_task_id='tb1'
    return ledger


def test_region_keeps_direct_sibling_before_older_other_region():
    ledger=two_regions();scheduler=TaskScheduler()
    assert scheduler.choose(ledger).task_id=='tb1'
    ledger.tasks['tb1'].status='done';ledger.operations['b1'].status='verified';ledger.current_task_id=''
    assert scheduler.choose(ledger).task_id=='tb2'


def test_model_focus_request_cannot_escape_active_work_region():
    ledger=two_regions();scheduler=TaskScheduler();scheduler.choose(ledger)
    before=deepcopy(ledger.snapshot())
    with pytest.raises(ValueError,match='工作Region'):
        scheduler.select_visible_operation(ledger,ledger.operations['o1'].canonical_operation_id,'New nearby branch')
    assert ledger.snapshot()==before
    assert scheduler.select_visible_operation(ledger,'cb2','Continue direct sibling').task_id=='tb2'


def test_foreground_survey_serves_work_region_without_releasing_it():
    ledger=two_regions();scheduler=TaskScheduler();scheduler.choose(ledger)
    ledger.tasks['tb1'].status='done';ledger.operations['b1'].status='verified';ledger.current_task_id=''
    ledger.states['s1'].survey_complete=False
    survey=ledger.survey_task('s1');survey.status='pending'
    assert scheduler.choose(ledger) is survey
    assert scheduler.work_region_id=='r2'
    survey.status='done';ledger.states['s1'].survey_complete=True
    assert scheduler.choose(ledger).task_id=='tb2'
    assert not any(e['kind']=='region_work_closed' for e in ledger.events)


@pytest.mark.parametrize('surveyed', [True, False])
@pytest.mark.parametrize('declared', [True, False])
def test_work_region_keeps_routed_target_over_older_zero_hop_external_task(surveyed, declared):
    from .explore_fixtures import _contextual_region_route_ledger
    from gui_rewalk.src.core.explore.region_routes import plan_region_route
    ledger=_contextual_region_route_ledger()
    ledger.current_state_id='s-alarm';ledger.current_page_id='p-alarm'
    ledger.operations['o-duration'].status='pending'
    source=ledger.operations['o-alarm']
    ledger.operations['outside']=replace(source,operation_id='outside',canonical_operation_id='co-outside',
        element_id='outside-owner',status='pending',target='Independent local task')
    ledger.elements['outside-owner']=replace(ledger.elements[source.element_id],element_id='outside-owner',operation_ids=['outside'])
    ledger.canonical_operations['co-outside']=CanonicalOperation('co-outside',source.region_id,source.action,'Independent local task',['outside'])
    ledger.region_variants[source.variant_id].operation_ids.append('outside')
    ledger.region_variants[source.variant_id].element_ids.append('outside-owner')
    ledger.regions[source.region_id].operation_ids.append('outside')
    ledger.regions[source.region_id].element_ids.append('outside-owner')
    target=Task('target','explore_operation','active','s-alarm-editor','o-duration',created_seq=100)
    external=Task('external','explore_operation','pending','s-alarm','outside',created_seq=1)
    ledger.tasks[target.task_id]=target;ledger.tasks[external.task_id]=external
    ledger.current_task_id=target.task_id
    scheduler=TaskScheduler();assert scheduler.choose(ledger) is target
    work=ledger.operations['o-duration'].region_id
    if declared:
        scheduler.declare_region(work,operations=[ledger.operations['o-duration'].canonical_operation_id])
    target.status='pending';ledger.current_task_id=''
    ledger.states['s-alarm'].survey_complete=surveyed
    route=plan_region_route(ledger,current_state_id='s-alarm',target_region_id=work,target_operation_id='o-duration')
    assert route['status']=='ready' and len(route['steps'])>0
    from gui_rewalk.src.core.explore.status import current_operation_binding
    assert current_operation_binding(ledger,'outside') is not None
    assert current_operation_binding(ledger,'o-duration') is None
    assert scheduler.choose(ledger) is target
    assert scheduler.work_region_id==work
    assert external.status=='pending'
    assert not any(e['kind']=='region_work_closed' for e in ledger.events)


def test_model_cannot_expand_declared_direct_scope():
    ledger=two_regions();scheduler=TaskScheduler()
    scheduler.declare_region('r2',operations=['cb1'])
    scheduler.choose(ledger);before=deepcopy(ledger.snapshot())
    with pytest.raises(ValueError,match='工作Region'):
        scheduler.select_visible_operation(ledger,'cb2','New same-Region task outside this round')
    assert ledger.snapshot()==before


def test_runtime_exposes_work_region_separate_from_frontground(tmp_path):
    ledger=two_regions()
    runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=_Agent([]),max_actions=1)
    runtime.ledger=ledger
    task=runtime.scheduler.choose(ledger)
    context=runtime._context(task,'target')
    assert context['工作区块']['region_ref']=='r2'
    assert context['工作区块']['coverage']['registered']==2
    assert context['任务相对环境']['physical_state_ref']=='s1'
    assert context['任务相对环境']['work_region_ref']=='r2'


def test_recorded_without_pending_is_not_direct_completion(tmp_path):
    ledger=two_regions();runtime=ExplorationRuntime(env=_Env(_png('white'),_png('white')),app_name='fixture',platform='desktop',
        output_root=str(tmp_path),agent=_Agent([]),max_actions=1)
    runtime.ledger=ledger;task=runtime.scheduler.choose(ledger)
    ledger.operations['b2'].status='recorded';ledger.tasks['tb2'].status='done'
    view=runtime._context(task,'target')['工作区块']['coverage']
    assert view['observed_only']==1
    assert view['direct_complete'] is False


def test_parent_direct_completion_does_not_wait_for_child():
    from gui_rewalk.src.core.explore.region_work import region_coverage
    ledger=two_regions();scheduler=TaskScheduler();scheduler.choose(ledger)
    ledger.operations['b1'].status=ledger.operations['b2'].status='verified'
    # The other existing Region becomes an unfinished child; no graph conversion.
    ledger.state_occurrences('s1')[0].parent_occurrence_id='rb'
    coverage=region_coverage(ledger,'r2')
    assert coverage['registered']==coverage['verified']==2
    assert coverage['direct_complete']
    assert coverage['child_regions_unfinished']==1
    next_task=scheduler.choose(ledger)
    assert scheduler.last_region_exit['status']=='complete'
    assert next_task.operation_id=='o1' and scheduler.work_region_id=='r1'
    assert ledger.operations['o1'].status!='verified'


def test_declared_scope_keeps_observation_condition_and_restriction_distinct():
    from gui_rewalk.src.core.explore.region_work import region_coverage
    ledger=two_regions()
    declaration={'operations':['cb1','cb2'],'conditions':{'cb1':'Needs a different selected tab'},
                 'restricted':{'cb2':'Outside authorized interaction'}}
    before=deepcopy(ledger.snapshot())
    coverage=region_coverage(ledger,'r2',declaration)
    assert coverage['pending_condition']==coverage['restricted']==1
    assert not coverage['direct_complete']
    assert ledger.snapshot()==before


def test_no_runnable_direct_task_parks_without_claiming_completion():
    ledger=two_regions();scheduler=TaskScheduler();scheduler.choose(ledger)
    for i in [1,2]:
        ledger.tasks[f'tb{i}'].status='done';ledger.operations[f'b{i}'].status='recorded'
    ledger.current_task_id=''
    selected=scheduler.choose(ledger)
    assert selected.operation_id=='o1'
    assert scheduler.last_region_exit['status']=='blocked'
    assert scheduler.last_region_exit['coverage']['observed_only']==2
    assert any('direct_region_scope' in gap for gap in scheduler.gaps(ledger))


def test_alarm_new_applicable_binding_reuses_deferred_task_without_erasing_no_effect():
    from .explore_fixtures import _ledger_with_current_canonical_binding
    from gui_rewalk.src.core.explore.inventory import _ensure_operation_task
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from gui_rewalk.src.core.explore.status import current_operation_binding
    ledger,task=_ledger_with_current_canonical_binding(executable=False)
    ledger.elements['el1'].name=ledger.elements['el2'].name='Alarm'
    ledger.states['s1'].name='Alarm selected';ledger.states['s2'].name='World Clock selected'
    ledger.tasks.pop('t-current')
    task.status='deferred';ledger.operations['o1'].status='deferred'
    ledger.attempts['selected-no-effect']=ActionAttempt('selected-no-effect',task.task_id,'s1','execute',
        {'kind':'click','operation_ref':'o1','owner_ref':'el1'},'before.png',outcome='no_effect',target_state_id='s1')
    ledger.current_task_id=''
    _ensure_operation_task(ledger,ledger.operations['o2'],state_id='s2')
    assert task.status=='deferred'  # no applicable current binding yet
    ledger.operations['o2'].status='pending'  # fresh, approved observation in World Clock
    _ensure_operation_task(ledger,ledger.operations['o2'],state_id='s2')
    assert task.status=='pending' and task.operation_id=='o2'
    assert current_operation_binding(ledger,task.operation_id).element_id=='el2'
    assert ledger.attempts['selected-no-effect'].outcome=='no_effect'
    assert ledger.operations['o1'].status=='deferred'


@pytest.mark.parametrize('reachable',[True,False])
def test_alarm_route_requires_applicable_source_not_selected_deferred_binding(reachable):
    from .explore_fixtures import _ledger_with_current_canonical_binding
    from gui_rewalk.src.core.explore.models import ActionAttempt, Transition
    from gui_rewalk.src.core.explore.region_routes import plan_region_route
    ledger,task=_ledger_with_current_canonical_binding()
    ledger.current_state_id='s1';ledger.operations['o1'].status='deferred'
    ledger.operations['o1'].reason='Alarm already selected; verify from World Clock'
    ledger.operations['world']=replace(ledger.operations['o1'],operation_id='world',canonical_operation_id='co-world',
        element_id='world-control',status='verified',target='World Clock')
    ledger.elements['world-control']=replace(ledger.elements['el1'],element_id='world-control',operation_ids=['world'])
    ledger.region_variants['rv1'].operation_ids.append('world');ledger.region_variants['rv1'].element_ids.append('world-control')
    ledger.regions['r1'].operation_ids.append('world');ledger.regions['r1'].element_ids.append('world-control')
    ledger.canonical_operations['co-world']=CanonicalOperation('co-world','r1','click','World Clock',['world'])
    ledger.attempts['selected-no-effect']=ActionAttempt('selected-no-effect',task.task_id,'s1','execute',
        {'kind':'click','operation_ref':'o1'},'selected.png',outcome='no_effect',target_state_id='s1')
    if reachable:
        action={'kind':'click','operation_ref':'world','owner_ref':'world-control'}
        ledger.attempts['world-proof']=ActionAttempt('world-proof','','s1','execute',action,'before.png',
            after_ref='after.png',outcome='success',target_state_id='s2')
        ledger.transitions.append(Transition('world-edge','s1','s2','world-proof',action,'World Clock visible'))
        ledger.event('region_effects_reported',attempt_ref='world-proof',changes=[{'region_ref':'r1','change':'updated','cause':'action'}])
    route=plan_region_route(ledger,current_state_id='s1',target_region_id='r1',target_operation_id='o2')
    assert route['status']==('ready' if reachable else 'unreachable')
    if reachable:assert route['steps'][0]['operation_ref']=='world'
    from gui_rewalk.src.core.explore.status import build_task_view
    task.operation_id='o2';task.state_id='s2'
    card=build_task_view(ledger,task)
    assert card['element_ref']==''
    if reachable:assert 'world-control' in card['instruction']
    assert ledger.attempts['selected-no-effect'].outcome=='no_effect'


def test_declared_exit_is_after_other_direct_work_and_scope_cannot_shrink():
    ledger=two_regions();scheduler=TaskScheduler()
    scheduler.declare_region('r2',operations=['cb1','cb2'],exit_operations=['cb1'])
    assert scheduler.choose(ledger).task_id=='tb2'
    with pytest.raises(ValueError,match='scope'):
        scheduler.declare_region('r2',operations=['cb2'])


def test_temporary_child_front_does_not_change_work_region_and_failed_return_parks():
    from gui_rewalk.src.core.explore.models import PageState,ActionAttempt,Transition
    ledger=two_regions();scheduler=TaskScheduler();scheduler.choose(ledger)
    ledger.tasks['tb1'].status='done';ledger.operations['b1'].status='verified';ledger.current_task_id=''
    ledger.states['child']=PageState('child','p1','Child popup','', 'child.png',[],True,1)
    ledger.current_state_id='child'
    ledger.attempts['entered']=ActionAttempt('entered','tb1','s1','execute',{'kind':'click','operation_ref':'b1'},'before.png',outcome='success',target_state_id='child')
    ledger.transitions.append(Transition('entered-edge','s1','child','entered',{'kind':'click','operation_ref':'b1'},'Child shown'))
    assert scheduler.choose(ledger).task_id=='tb2'
    assert scheduler.work_region_id=='r2'
    ledger.attempts['return-failed']=ActionAttempt('return-failed','tb2','child','route',{'kind':'back'},'before.png',outcome='no_effect',target_state_id='child')
    scheduler.choose(ledger)
    assert scheduler.last_region_exit['region_ref']=='r2'
    assert scheduler.last_region_exit['status']=='blocked'
    assert ledger.attempts['return-failed'].outcome=='no_effect'


def test_alarm_is_verified_from_world_clock_after_selected_no_effect(tmp_path):
    from .explore_fixtures import _ledger_with_current_canonical_binding, _known_screen, _turn
    from gui_rewalk.src.core.explore.models import ActionAttempt
    from gui_rewalk.src.core.explore.contracts import parse_turn
    from gui_rewalk.src.core.explore.location import bind_screen
    from gui_rewalk.src.core.explore.inventory import _ensure_operation_task
    ledger,task=_ledger_with_current_canonical_binding()
    ledger.tasks.pop('t-current');ledger.current_state_id='s1'
    ledger.operations['o1'].status='deferred';task.status='deferred'
    ledger.operations['o1'].reason='Alarm selected; verify in another applicable state'
    ledger.attempts['old-selected']=ActionAttempt('old-selected',task.task_id,'s1','execute',
        {'kind':'click','operation_ref':'o1','owner_ref':'el1'},'old.png',outcome='no_effect',target_state_id='s1')
    _ensure_operation_task(ledger,ledger.operations['o2'],state_id='s2')
    ledger.operations['world']=replace(ledger.operations['o1'],operation_id='world',canonical_operation_id='co-world',
        element_id='world-control',status='verified',target='World Clock',parameter_status='none')
    ledger.elements['world-control']=replace(ledger.elements['el1'],element_id='world-control',operation_ids=['world'])
    ledger.region_variants['rv1'].operation_ids.append('world');ledger.region_variants['rv1'].element_ids.append('world-control')
    ledger.regions['r1'].operation_ids.append('world');ledger.regions['r1'].element_ids.append('world-control')
    ledger.canonical_operations['co-world']=CanonicalOperation('co-world','r1','click','World Clock',['world'])
    env=_Env(_png('white'),_png('blue'))
    runtime=ExplorationRuntime(env=env,app_name='fixture',platform='desktop',output_root=str(tmp_path),agent=_Agent([]),max_actions=2)
    runtime.ledger=ledger
    for owner,destination,color in [('world-control','s2','blue'),('el2','s1','white')]:
        action=parse_turn(_turn(screen=_known_screen(),action={'kind':'click','owner_ref':owner,'point_1000':[500,500]}),has_pending_action=False).action
        bound=runtime._bind_action(task,action)
        assert runtime._validate_action(task,bound)==''
        before=env._get_obs()['screenshot'];env.after=_png(color)
        obs=runtime._execute(task=task,action=bound,screenshot=before)
        screen={**_known_screen(),'state_ref':destination}
        receipt=parse_turn(_turn(screen=screen,previous={'attempt_ref':runtime.pending_attempt_id,
            'element_actions':[{'element_ref':owner,'action':'click','completed':True}],
            'region_actions':[],'function_info':[],'region_effects':[],
            'parameter_info':{'status':'none','summary':'Navigation has no parameter'},'reason':'Simulated target tab appeared'}),has_pending_action=True)
        located=bind_screen(runtime.ledger,receipt.screen,screenshot_ref='fixture-after.png');assert located.ok
        runtime.ledger=located.ledger
        runtime._settle_pending(receipt,screenshot=obs['screenshot'],frame_ref='fixture-after.png')
    assert len(env.actions)==2
    assert runtime.ledger.operations['o2'].status=='verified'
    assert runtime.ledger.attempts['old-selected'].outcome=='no_effect'
    new=list(runtime.ledger.attempts.values())[-1]
    assert new.action['operation_ref']=='o2' and new.source_state_id=='s2' and new.outcome=='success'
