"""Current Control structure: facts, groups, appearances and real entry points."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from regrow.paths import SOURCE_ROOT
from regrow.records.object_store import Records, owned_controls, owned_tasks, observation_history, save, load
from regrow.records.region_evidence import new_region
from regrow.records.control_records import normalize, merge, group_name, set_group, aliases
from regrow.records.control_knowledge import update, parameters, put_parameter, remove_parameter, confirmed, text
from regrow.records.tasks import store_knowledge, store_findings, read


def setup():
    data = Records({'r0001': new_region('r0001', '工具栏'), 'r0002': new_region('r0002', '另一页面')})
    return data, data['r0001']


def test_import_places_control_facts_once_and_keeps_old_source():
    source = {'name': '搜索', 'possible_purpose': '搜索内容', 'constraints': {'关键词': {'name': '关键词', 'description': '按名称匹配'}},
              'list_group': '搜索入口', 'merged_records': [{'id':'c0009','name':'旧搜索'}],
              'shared_control_ref': {'region':'r0001','name':'旧共享'}, 'image':'old.png'}
    original = deepcopy(source)
    data = Records({'r0001': {**new_region('r0001','工具栏'), 'controls': {'c0001': source}}})
    c = data.controls['c0001']
    assert set(c) == {'name','description','knowledge','image','jump_to','may_open_content','needs_exploration'}
    assert c['knowledge'][0]['description'] == '搜索内容'
    assert c['knowledge'][0]['constraints']['关键词']['description'] == '按名称匹配'
    assert c['image'] == [{'path':'old.png','conditions':[]}]
    assert group_name(data['r0001'],'c0001') == '搜索入口'
    assert aliases(c)[0]['id'] == 'c0009'
    assert source == original


def test_guess_and_confirmed_fact_share_one_field_and_keep_rules():
    data,r=setup();owned_controls(r)['c0001']={'name':'搜索','knowledge':[{'description':'可能搜索','conditions':[],'constraints':{'关键词':{'name':'关键词','description':'输入文本'}}}]}
    c=data.controls['c0001'];assert not confirmed(c)
    owned_tasks(r)['功能探索']={'control':'c0001','task_type':'function','status':'pending'}
    store_knowledge(owned_tasks(r)['功能探索'],[{'description':'展开搜索输入框','conditions':[]}],{'basis':'explored','attempt':'a1'})
    assert text(confirmed(c))=='展开搜索输入框'
    assert parameters(c)['关键词']['description']=='输入文本'
    assert 'possible_purpose' not in c and 'constraints' not in c


def test_parameter_task_reads_current_nested_rules_after_roundtrip(tmp_path):
    data,r=setup();owned_controls(r)['c0001']={'name':'搜索','knowledge':[{'description':'筛选列表','conditions':[]}]}
    owned_tasks(r)['参数探索']={'control':'c0001','task_type':'parameter','status':'pending'}
    task=owned_tasks(r)['参数探索']
    store_findings(task,[{'name':'匹配方式','description':'按名称包含匹配'}],{'basis':'explored','attempt':'a1'})
    def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    save(data,tmp_path/'snapshot',write);back=load(tmp_path/'snapshot')
    c=back.controls['c0001'];assert 'constraints' not in c
    assert c['knowledge'][0]['constraints']['匹配方式']['description']=='按名称包含匹配'
    assert read(owned_tasks(back['r0001'])['参数探索'],'findings')['匹配方式']['source']['attempt']=='a1'


def test_conditional_rule_branches_do_not_overwrite_each_other():
    c={'knowledge':[{'description':'功能A','conditions':['模式A'],'constraints':{'输入':{'name':'输入','description':'规则A'}}},
                    {'description':'功能B','conditions':['模式B'],'constraints':{'输入':{'name':'输入','description':'规则B'}}}]}
    values=parameters(c);assert len(values)==2
    ref=next(k for k,v in values.items() if v['description']=='规则B')
    put_parameter(c,ref,{'name':'输入','description':'修订B'})
    assert {v['description'] for v in parameters(c).values()}=={'规则A','修订B'}
    remove_parameter(c,ref)
    assert [v['description'] for v in parameters(c).values()]==['规则A']


def test_parameter_change_does_not_unconfirm_same_function():
    c={};update(c,[{'description':'筛选列表','conditions':[]}],{'task_ref':'r1/t','attempt':'a1'})
    put_parameter(c,'关键词',{'name':'关键词','description':'名称匹配'})
    assert text(confirmed(c))=='筛选列表'


def test_groups_follow_each_region_not_the_shared_control():
    data,r=setup();owned_controls(r)['c0001']={'name':'条目'};owned_controls(data['r0002']).setdefault('c0001',{})
    set_group(r,'c0001','列表A');set_group(data['r0002'],'c0001','列表B')
    assert group_name(r,'c0001')=='列表A' and group_name(data['r0002'],'c0001')=='列表B'
    del owned_controls(r)['c0001']
    assert 'list_groups' not in r and group_name(data['r0002'],'c0001')=='列表B'
    assert 'list_group' not in data.controls['c0001']


def test_identity_merge_keeps_alias_in_history_and_old_request_positions():
    from regrow.recognition.control_indexes import after_record_edit
    data,r=setup();owned_controls(r)['c0001']={'name':'搜索'};owned_controls(r)['c0002']={'name':'旧搜索'}
    set_group(r,'c0002','搜索入口');merge(data,{},'r0001',['c0002'],'c0001')
    assert 'merged_records' not in data.controls['c0001']
    assert any(row['id']=='c0002' for row in aliases(data.controls['c0001']))
    assert group_name(r,'c0001')=='搜索入口'
    from tests.test_control_indexes import request
    original=request();original['control_indexes']=['c0002'];fresh=request()
    assert after_record_edit(original,fresh,data)['control_indexes'][0]=='c0001'


def test_old_behavior_group_does_not_become_shared_physical_identity():
    from regrow.records.shared_controls import view,refresh
    data,r=setup();owned_controls(r)['c0001']={'name':'入口A','shared_control_ref':{'region':'r0001','name':'同类入口'}}
    owned_controls(data['r0002'])['c0002']={'name':'入口B','shared_control_ref':{'region':'r0001','name':'同类入口'}}
    r['shared_controls']={'同类入口':{'name':'同类入口','status':'confirmed','members':[{'region':'r0001','control':'c0001'},{'region':'r0002','control':'c0002'}],'proposal_evidence':'旧行为关系'}}
    normalize(data);refresh(data)
    assert len(data.controls)==2 and view(data,'r0002','c0002')['status']=='confirmed'
    assert all('shared_control_ref' not in c for c in data.controls.values())


def test_new_control_wire_uses_approved_names_and_array_knowledge():
    from regrow.traversal.result_updater import build_update_request
    q=build_update_request(SOURCE_ROOT,{},['before','after'])
    fields=q['response_schema']['properties']['controls']['items']['properties']
    assert {'description','knowledge','add_image','image_conditions'} <= set(fields)
    assert not {'possible_purpose','icon_bbox','icon_appearance','icon_image','constraints'} & set(fields)
    assert fields['knowledge']['type']=='array'
    from regrow.prompts.response_example import complete
    assert '```json' in complete(q['response_schema'],q)


def test_readable_guide_exposes_dependency_fields_and_long_enums():
    from regrow.prompts.response_example import guide
    choices=[str(i) for i in range(11)]
    schema={'type':'object','properties':{'blocked_by':{'type':'string','enum':choices},'dependency_updates':{'type':'array','items':{'type':'object','properties':{k:{'type':'string'} for k in ['region','task','evidence']}}}}}
    output=guide(schema)
    assert '"10"' in output and all(k in output for k in ['region','task','evidence'])


def test_stored_image_gallery_rebases_and_old_state_can_match(tmp_path):
    from regrow.recognition.identity_templates import variants
    from regrow.recognition.history_matching import match_region
    from regrow.recognition import matching
    data,r=setup();owned_controls(r)['c0001']={'name':'播放'};c=data.controls['c0001']
    for label in ['play','pause']:
        p=tmp_path/(label+'.png');im=Image.new('RGB',(20,20),'white');ImageDraw.Draw(im).rectangle((4,4,15,15),fill='black' if label=='play' else 'blue');im.save(p)
        observation_history(c).append({'image':str(p),'image_conditions':[label], 'evidence':{'source_call':label,'source_field':'/controls/0'}})
    normalize(data)
    assert [v['conditions'] for v in c['image']]==[['play'],['pause']]
    assert 'icon_image' not in c
    def locate(path):return {'accepted':Path(path).name=='play.png','score':1 if Path(path).name=='play.png' else 0,'box':[2,2,22,22],'candidates':[]}
    row=match_region('r0001',r,locate,None)
    assert row['matched_controls']==1 and len(row['anchors'])==1
    def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    save(data,tmp_path/'snapshot',write);restored=load(tmp_path/'snapshot')
    assert len(restored.controls['c0001']['image'])==2
    assert len(variants(restored.controls['c0001']))==2


def test_withdrawal_removes_unsupported_route_but_retains_independent_visit():
    from regrow.records.tasks import store_object_entry, invalidate_products
    from regrow.records.control_routes import with_source
    data,r=setup();owned_controls(r)['c0001']={'name':'入口'};c=data.controls['c0001']
    store_object_entry(c,{'region':'r0002','conditions':[],'meaning':'进入页面','attempt':'a1'})
    assert set(c['jump_to'][0])=={'region','conditions'}
    invalidate_products(c,'a1',{})
    assert c['jump_to']==[]
    for attempt in ['a2','a3']:
        store_object_entry(c,{'region':'r0002','conditions':[],'meaning':'进入页面','attempt':attempt})
    invalidate_products(c,'a3',{})
    assert len(c['jump_to'])==1 and with_source(c,c['jump_to'][0])['attempt']=='a2'


def test_imported_guess_does_not_erase_parameter_product_from_old_task():
    region={**new_region('r0001','搜索区'),'controls':{'c0001':{'name':'搜索','possible_purpose':'搜索内容'}},
            'tasks':{'参数任务':{'name':'参数任务','control':'c0001','task_type':'parameter','status':'done',
                'findings':{'关键词':{'name':'关键词','description':'按名称匹配','source':{'basis':'observation_only','source_call':'5'}}}}}}
    data=Records({'r0001':region})
    assert parameters(data.controls['c0001'])['关键词']['description']=='按名称匹配'


def test_identity_merge_preserves_other_condition_guesses():
    from regrow.records.control_knowledge import merge as merge_knowledge
    target={};source={}
    update(target,[{'description':'添加世界时钟','conditions':['世界时钟']}],{'task_ref':'r1/t','attempt':'a1'})
    update(target,[{'description':'可能添加闹钟','conditions':['闹钟']}],{'basis':'discovery','source_call':'2'})
    update(source,[{'description':'新增城市','conditions':['世界时钟']}],{'task_ref':'r1/u','attempt':'a2'})
    merge_knowledge(target,source)
    assert len(target['knowledge'])==2
    assert next(row for row in target['knowledge'] if row['conditions']==['闹钟'])['description']=='可能添加闹钟'
    assert [row['conditions'] for row in confirmed(target)]==[['世界时钟']]


@pytest.mark.parametrize('later',['parameter','discovery'])
def test_identity_merge_reuses_accepted_function_source(later):
    from regrow.records.control_knowledge import merge as merge_knowledge, evidence
    target={};source={}
    row={'description':'筛选列表','conditions':[]}
    update(target,[row],{'task_ref':'r1/t','attempt':'a1'})
    if later=='parameter':
        put_parameter(target,'关键词',{'name':'关键词','description':'名称包含匹配'})
    else:
        update(target,[row],{'basis':'discovery','source_call':'2'})
    update(source,[{'description':'按名称查找','conditions':[]}],{'task_ref':'r1/u','attempt':'a2'})
    merge_knowledge(target,source)
    assert text(confirmed(target))=='筛选列表\n按名称查找'
    assert {v['attempt'] for v in evidence(target)['sources']}=={'a1','a2'}
    if later=='parameter':
        assert parameters(target)['关键词']['description']=='名称包含匹配'


def test_appearance_union_keeps_ambiguous_positions_and_truncation():
    from regrow.recognition.matching import match_appearances
    boxes=[[0,0,10,10],[20,0,30,10],[40,0,50,10]]
    values={'a':{'accepted':True,'score':1,'box':boxes[0],'candidates':[]},
            'b':{'accepted':False,'score':1,'box':boxes[1],
                 'candidates':[{'box':box,'score':1} for box in boxes[1:]]}}
    hit=match_appearances([{'image':v} for v in values],values.get)
    assert not hit['accepted'] and len(hit['candidates'])==3
    values['a']['accepted']=False;values['a']['candidates']=[{'box':boxes[0],'score':1}]
    hit=match_appearances([{'image':v} for v in values],values.get)
    assert not hit['accepted'] and len(hit['candidates'])==3
    values['a'].update(accepted=True,candidates_truncated=True)
    hit=match_appearances([{'image':'a'}],values.get)
    assert not hit['accepted'] and hit['candidates_truncated']


def test_readable_guide_exposes_nullable_boolean_and_nested_action_enum():
    from regrow.prompts.response_example import guide
    from regrow.records.task_updates import schema
    body=guide({'type':'object','properties':{
        'regions':{'type':'array','items':{'type':'object','properties':{'context_matches':{'type':['boolean','null']}}}},
        'task_update':{'type':'array','items':schema(['function'])}}})
    assert 'context_matches=true/false/null' in body
    assert 'next_action对象字段：region、control、action="click"/' in body
    assert '"wait"' in body
