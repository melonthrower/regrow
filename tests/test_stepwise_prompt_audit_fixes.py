import json
from copy import deepcopy
import pytest
from tests.test_stepwise_region_tasks import tasks,row,proposal
from tests.test_stepwise_resume_route import ROOT,fixture


def test_input_task_is_accepted_by_final_schema_and_registration():
    _,records,state=fixture();m=tasks();r=records['menu']
    op={**row(),'action':'input_text','task_type':'parameter','findings':[]}
    q=m.plan_request(ROOT,records,state,'menu')
    import jsonschema
    jsonschema.validate(proposal([op]),q['response_schema'])
    m.apply_plan(r,proposal([op]),'input');assert r['tasks'][op['name']]['action']=='input_text'


def test_incremental_inventory_preserves_old_tasks_without_repeating_them():
    _,records,state=fixture();m=tasks();r=records['menu'];m.apply_plan(r,proposal([row()]),'first')
    before=deepcopy(r['tasks']);r['controls']['new']={'name':'搜索框','action_refs':[],'observations':[]}
    p=proposal([{**row('搜索反馈','搜索框'),'action':'input_text','task_type':'parameter','findings':[]}])
    q=m.plan_request(ROOT,records,state,'menu')
    m.helper('registration_diagnostics').check('task_proposal',q,p,records)
    m.apply_plan(r,p,'second')
    assert r['tasks']['查看内容']==before['查看内容'] and m.coverage(r)['inventory_complete']
    m.apply_plan(r,proposal([]),'repeat');assert m.coverage(r)['inventory_complete']


def test_task_context_labels_current_and_historical_controls():
    _,records,state=fixture();state['observation']['control_refs']=[]
    q=tasks().plan_request(ROOT,records,state,'menu');d=json.loads(q['user_prompt'])
    assert d['控件'][0]['当前定位']=='本轮未定位，仅为历史记录'
    assert '不必重报' in q['system_prompt']


def test_no_focus_has_unambiguous_null_contract(tmp_path):
    from PIL import Image
    p=tmp_path/'frame.png';Image.new('RGB',(60,100),'white').save(p)
    q=tasks().helper('discovery_step').prepare(ROOT,{}, {'working_region':None},str(p))
    assert q['response_schema']['properties']['focus_presence']['type']=='null'
    assert 'null' in q['system_prompt']


def test_updates_have_no_discovery_identity_instruction():
    q=tasks().helper('update_step').build_update_request(ROOT,{},['before','after'])
    assert '使用same' not in q['system_prompt']
    assert '为归属引用' in q['system_prompt']


def test_function_context_does_not_assert_all_observations_are_settable():
    from tests.test_region_function_inventory import alarm_region
    _,r,_=alarm_region();q=tasks().helper('region_functions').request(ROOT,r,{'observation':{'id':'test'}})
    d=json.loads(q['user_prompt'])
    assert '可设置约束' not in d and '已记录属性（待甄别）' in d
    assert '只读' in q['system_prompt']


def test_full_examples_validate_against_actual_reply_schemas():
    import jsonschema
    m=tasks();recovery=m.helper('recovery');action=m.helper('action_commands')
    for relative,validator in [('动作/动作空间与字段.prompt',action.validate),('异常处理/恢复输出.prompt',recovery.validate)]:
        rows=[json.loads(line) for line in (ROOT/'遍历prompt'/relative).read_text().splitlines() if line.startswith('{')]
        assert len(rows)>=2
        for row in rows:validator(row)


def test_discovery_only_discloses_accepted_position():
    m=tasks().helper('discovery_step')
    v=m.match_context({'accepted':True,'box':[1,2,3,4],'candidates':[{'box':[5,6,7,8]}]})
    assert v['候选位置']==[[1,2,3,4]]
