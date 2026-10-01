"""A discovered foreground must retain an active multi-step task's purpose."""
from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import ROOT, tasks, proposal, row
from tests.test_stepwise_resume_route import fixture


def case(kind='parameter'):
    flow, records, state = fixture()
    module = tasks()
    records['middle']['controls'] = {}
    module.apply_plan(records['middle'], proposal([]), 'child')
    module.apply_plan(records['main'], proposal([row('调查参数', '打开主体')]), 'parent')
    task = records['main']['tasks']['调查参数']
    task['task_type'] = kind
    if kind == 'scroll':
        task.update(control=None, action='scroll')
    state.update(working_region='main', interactive_regions=['middle'],
        reason='navigation_from_foreground', active_task={'region': 'main', 'name': '调查参数'})
    state['observation']['control_refs'] = []
    return flow, module, records, state, task


@pytest.mark.parametrize('kind', ['parameter', 'scroll'])
def test_discovered_child_keeps_active_multistep_task(kind):
    flow, module, records, state, _ = case(kind)
    original = deepcopy((records, state))
    base = flow.assemble_context(ROOT, records, state, 'main')
    assert base['navigation_advice']
    request = module.attach(ROOT, records, state, 'main', base)
    assert request['source']['task_name'] == '调查参数'
    assert request['source']['task_region'] == 'main'
    assert request['source']['region'] == 'middle'
    assert not request.get('navigation_advice')
    assert request['allow_scroll']
    assert (records, state) == original


@pytest.mark.parametrize('condition', ['no_active', 'blocked', 'excluded', 'single_action'])
def test_ordinary_navigation_keeps_priority_without_allowed_multistep_task(condition):
    flow, module, records, state, task = case()
    if condition == 'no_active':
        state.pop('active_task')
    elif condition == 'blocked':
        task['status'] = 'blocked'
    elif condition == 'excluded':
        records['main']['out_of_scope_reason'] = 'Outside this run scope'
    else:
        task.update(task_type='single_action', attempts=['earlier'])
    base = flow.assemble_context(ROOT, records, state, 'main')
    assert module.attach(ROOT, records, state, 'main', base) is base
