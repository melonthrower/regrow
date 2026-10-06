import importlib.util
import json
from pathlib import Path
from copy import deepcopy
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module():
    s=importlib.util.spec_from_file_location('registration',ROOT/'register_update.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def fixture(tmp_path):
    run=tmp_path/'run';(run/'calls/0001').mkdir(parents=True);(run/'action_attempts/a1').mkdir(parents=True);(run/'graph_snapshots').mkdir()
    region={'id':'r1','proposal':{'name':'Menu','description':'Menu content'}}
    controls=[{'id':'c1','owner_ref':'r1','proposal':{'text':'Policy'}},{'id':'c2','owner_ref':'r1','proposal':{'text':'Settings'}}]
    graph={'regions':[region],'controls':controls,'observations':[{'id':'o1','region_refs':['r1'],'control_refs':['c1','c2']},{'id':'o2','region_refs':[],'control_refs':[]}],
           'action_edges':[{'attempt':'a1','source_region':'r1','source_control':'c1','before_observation':'o1','after_observation':'o2','selection_call':'old','result_call':'old','delivery':'executed_receipt_zero','after_interactive_region_proposals':[],'model_result':{'status':'observed_effect'}}]}
    result={'foreground':{'description':'Browser','evidence':'image','uncertainty':''},'regions':[],'controls':[],'excluded':[],'uncertainties':['policy not seen'],
        'action_result':{'exception':'external_app','description':'Browser opened, policy unconfirmed','evidence':'images'},'previous_regions':[{'name':'Menu','state':'not_visible','evidence':'image'}],
        'working_context':{'region_name':'Menu','preserve_record':True,'reason':'unfinished'},
        'exploration_update':{'attempt_status':'executed','outcome':'unconfirmed','evidence':'records'},'handoff_summary':'Menu remains unfinished'}
    for p,d in [('calls/0001/response.json',result),('action_attempts/a1/receipt.json',{'exit_code':0}),('graph_snapshots/0001.json',graph)]:
        (run/p).write_text(json.dumps(d))
    return run,graph,result

def invoke(m,run):return m.commit_update(ROOT,run,'graph_snapshots/0001.json','0001','a1')

def read_region(run,pointer):return json.loads((run/pointer['snapshot']/'regions/r1/region.json').read_text())

def test_external_registers_control_effect_and_preserves_pending(tmp_path):
    m=module();run,g,r=fixture(tmp_path);old=(run/'graph_snapshots/0001.json').read_bytes()
    p=invoke(m,run);region=read_region(run,p)
    assert region['controls']['c1']['action_refs']==['a1']
    assert region['actions']['a1']['result']['exception']=='external_app'
    assert region['transitions']==[]
    assert region['actions']['a1']['delivery']=='executed_receipt_zero'
    assert region['controls']['c2']['action_refs']==[]
    state=json.loads((run/p['snapshot']/'runtime_state.json').read_text())
    assert state['update_status']=='committed' and state['next_action_mode']=='recover'
    assert state['working_region']=='r1' and state['interactive_regions']==[]
    assert (run/'graph_snapshots/0001.json').read_bytes()==old

def test_duplicate_reopen_does_not_append_action_or_history(tmp_path):
    m=module();run,_,_=fixture(tmp_path)
    p=invoke(m,run);before=(run/'knowledge_current.json').read_bytes()
    again=invoke(m,run)
    assert p==again and (run/'knowledge_current.json').read_bytes()==before
    assert len(read_region(run,p)['actions'])==1
    assert len(list((run/'knowledge_snapshots').iterdir()))==1

@pytest.mark.parametrize('bad',['unknown_entry','ambiguous_name','wrong_attempt','failed_receipt'])
def test_invalid_update_leaves_no_current_pointer(tmp_path,bad):
    m=module();run,g,r=fixture(tmp_path)
    if bad=='unknown_entry':r['exploration_update']['entry_name']='Missing'
    if bad=='ambiguous_name':g['regions'].append({'id':'r2','proposal':{'name':'Menu','description':''}})
    if bad=='wrong_attempt':g['action_edges'][0]['source_control']='missing'
    if bad=='failed_receipt':(run/'action_attempts/a1/receipt.json').write_text('{"exit_code":1}')
    (run/'calls/0001/response.json').write_text(json.dumps(r));(run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    with pytest.raises(ValueError):invoke(m,run)
    assert not (run/'knowledge_current.json').exists()

def test_internal_new_region_creates_source_edge_and_no_reverse(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    r['action_result']['exception']='none'
    r['regions']=[{'name':'Settings panel','previous_name':'','parent_index':None,'description':'panel','reason':'new','bbox':None}]
    r['controls']=[{'text':'Done','previous_name':'','region_index':0,'icon_appearance':'','state':'visible','possible_operation':'close','uncertainty':'untested','bbox':None,'icon_bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(r))
    p=invoke(m,run);source=read_region(run,p)
    assert source['transitions'][0]['source_control']=='c1'
    target=source['transitions'][0]['target_region']
    dest=json.loads((run/p['snapshot']/f'regions/{target}/region.json').read_text())
    assert dest['reached_by'][0]['source_region']=='r1'
    assert dest['transitions']==[] and len(dest['controls'])==1

def test_write_failure_does_not_publish(tmp_path,monkeypatch):
    m=module();run,_,_=fixture(tmp_path)
    original=m.write_json
    def fail(path,data):
        if path.name=='runtime_state.json':raise OSError('simulated write failure')
        return original(path,data)
    monkeypatch.setattr(m,'write_json',fail)
    with pytest.raises(OSError):invoke(m,run)
    assert not (run/'knowledge_current.json').exists()


def test_pointer_failure_can_finish_publication_on_retry(tmp_path,monkeypatch):
    m=module();run,_,_=fixture(tmp_path);original=m.write_json
    def fail(path,data):
        if path.name=='knowledge_current.pending.json':raise OSError('pointer interrupted')
        return original(path,data)
    monkeypatch.setattr(m,'write_json',fail)
    with pytest.raises(OSError):invoke(m,run)
    assert not (run/'knowledge_current.json').exists()
    monkeypatch.setattr(m,'write_json',original)
    p=invoke(m,run)
    assert json.loads((run/'knowledge_current.json').read_text())==p


def test_reassessment_keeps_one_attempt_and_old_replay_does_not_roll_back(tmp_path):
    m=module();run,_,r=fixture(tmp_path);first=invoke(m,run)
    r['action_result']['description']='Same evidence, refined description'
    (run/'calls/0002').mkdir();(run/'calls/0002/response.json').write_text(json.dumps(r))
    second=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a1')
    assert first!=second
    region=read_region(run,second)
    assert region['controls']['c1']['action_refs']==['a1'] and len(region['actions'])==1
    assert 'history' not in region
    assert read_region(run,first)['actions']['a1']['result']['description']=='Browser opened, policy unconfirmed'
    assert invoke(m,run)==first
    assert json.loads((run/'knowledge_current.json').read_text())==second


def test_new_visuals_saved_under_region_with_valid_evidence_paths(tmp_path):
    from PIL import Image
    m=module();run,g,r=fixture(tmp_path)
    Image.new('RGB',(60,60)).save(run/'after.png')
    g['action_edges'][0]['after_image']='after.png'
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    box={'left':1,'top':2,'right':40,'bottom':50}
    r['action_result']['exception']='none'
    r['regions']=[{'name':'New','previous_name':'','parent_index':None,'description':'new','reason':'visible','bbox':box}]
    r['controls']=[{'text':'Done','previous_name':'','region_index':0,'icon_appearance':'dot','state':'visible','possible_operation':'close','uncertainty':'unknown','bbox':box,'icon_bbox':{'left':2,'top':3,'right':8,'bottom':9}}]
    (run/'calls/0001/response.json').write_text(json.dumps(r))
    p=invoke(m,run);base=run/p['snapshot']/'regions/r0002'
    target=json.loads((base/'region.json').read_text())
    control=next(iter(target['controls'].values()))
    for visual in [target['observations'][-1],control['observations'][-1]]:
        assert (base/visual['image']).is_file() and (base/visual['source_image']).resolve()==(run/'after.png')
    assert (base/control['observations'][-1]['icon_image']).is_file()


def test_new_action_registers_from_binding_and_receipt_without_precreated_edge(tmp_path):
    m=module();run,g,r=fixture(tmp_path);g['action_edges']=[]
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    (run/'action_attempts/a1/binding.json').write_text(json.dumps({'status':'matched','region_ref':'r1','control_ref':'c1','observation_ref':'o1'}))
    (run/'action_attempts/a1/dispatch.json').write_text(json.dumps({'source_region':'r1','source_control':'c1','source_call':'choice'}))
    (run/'calls/0001/request.json').write_text(json.dumps({'screenshots':['before.png','after.png']}))
    for name in ['before.png','after.png']:(run/name).write_bytes(b'evidence reference only')
    p=invoke(m,run);region=read_region(run,p)
    assert region['controls']['c1']['action_refs']==['a1']
    assert region['actions']['a1']['result']['exception']=='external_app'


def test_named_records_keep_update_provenance_together(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    g['action_edges'][0]['region_changes']=[{'region_ref':'r1','state':'old_state','evidence':'old claim'}]
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    p=invoke(m,run);region=read_region(run,p)
    assert region.get('name')=='Menu'
    assert region['controls']['c1']['name']=='Policy'
    assert 'proposal' not in region['controls']['c1']
    assert 'exploration' not in region
    action=region['actions']['a1']
    assert action['region_changes']==[{'region':'r1','state':'not_visible','evidence':'image'}]
    assert action['evidence']['result_call']=='0001'
    assert 'old claim' not in json.dumps(action)


def test_rediscovery_rename_preserves_control_history_and_effect(tmp_path):
    m=module();run,g,r=fixture(tmp_path);first=invoke(m,run)
    r['action_result']['exception']='none'
    r['regions']=[{'name':'Menu','previous_name':'Menu','parent_index':None,'description':'updated menu','reason':'returned','bbox':None}]
    r['previous_regions'][0]['state']='changed_interactive'
    r['controls']=[{'text':'Privacy','previous_name':'Policy','region_index':0,'icon_appearance':'','state':'visible','possible_operation':'open','uncertainty':'','bbox':None,'icon_bbox':None}]
    (run/'calls/0002').mkdir();(run/'calls/0002/response.json').write_text(json.dumps(r))
    p=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a1')
    region=read_region(run,p);control=region['controls']['c1']
    assert control.get('name')=='Privacy'
    assert [o['text'] for o in control['observations']]==['Policy','Privacy']
    assert control['action_refs']==['a1']
    assert read_region(run,first)['controls']['c1']['name']=='Policy'


def test_current_context_reads_committed_effect_and_blocks_invisible_action(tmp_path):
    m=module();run,g,r=fixture(tmp_path);invoke(m,run)
    flow=m.sibling('stepwise_flow')
    assert hasattr(flow,'assemble_current_context')
    q=flow.assemble_current_context(ROOT,run,'r1')
    assert 'Browser opened, policy unconfirmed' not in q['dynamic_prompt']  # hidden-region history stays in its record
    assert q['progress']['controls_with_delivery']==1
    assert 'completion' not in q['progress']
    assert q['backend_candidates']==[]  # old visible geometry is not current
    assert q['action_ready'] is False
    assert all(x not in q['user_prompt'] for x in ['c1','r1','o1','a1'])


def test_discovery_publishes_same_record_shape_before_action(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    g['action_edges']=[];g['observations']=g['observations'][:1]
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    assert hasattr(m,'commit_discovery')
    p=m.commit_discovery(ROOT,run,'graph_snapshots/0001.json')
    region=read_region(run,p)
    assert region['name']=='Menu' and region['controls']['c1']['name']=='Policy'
    assert region['actions']=={} and region['controls']['c1']['action_refs']==[]
    assert region['functions']=={} and 'exploration' not in region
    q=m.sibling('stepwise_flow').assemble_current_context(ROOT,run,'r1')
    assert q['progress']['controls_without_record']==2 and not q['action_ready']
    assert q['stage']=='task_proposal'


@pytest.mark.parametrize('keep_legacy_graph',[True,False])
def test_next_action_can_start_from_newly_registered_region_without_old_graph_entry(tmp_path,keep_legacy_graph):
    m=module();run,g,r=fixture(tmp_path)
    g['action_edges']=[]
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    def attempt(aid,call,region,control,observation):
        folder=run/f'action_attempts/{aid}';folder.mkdir(exist_ok=True)
        (folder/'binding.json').write_text(json.dumps({'status':'matched','region_ref':region,'control_ref':control,'observation_ref':observation}))
        (folder/'dispatch.json').write_text(json.dumps({'source_region':region,'source_control':control,'source_call':'choice'}))
        (folder/'receipt.json').write_text('{"exit_code":0}')
        (run/f'calls/{call}').mkdir(exist_ok=True)
        (run/f'calls/{call}/request.json').write_text(json.dumps({'screenshots':['before.png','after.png']}))
        (run/f'calls/{call}/response.json').write_text(json.dumps(r))
    for name in ['before.png','after.png']:(run/name).write_bytes(b'evidence reference only')
    r['action_result']['exception']='none'
    r['regions']=[{'name':'Settings panel','previous_name':'','parent_index':None,'description':'panel','reason':'new','bbox':None}]
    r['controls']=[{'text':'Done','previous_name':'','region_index':0,'icon_appearance':'','state':'visible','possible_operation':'close','uncertainty':'untested','bbox':None,'icon_bbox':None}]
    attempt('a1','0001','r1','c1','o1');p=invoke(m,run)
    r['action_result']['exception']='external_app';r['regions']=[];r['controls']=[]
    r['previous_regions']=[{'name':'Settings panel','state':'not_visible','evidence':'gone'}]
    r['working_context']['region_name']='Settings panel'
    r['exploration_update'].update(entry_name='Done')
    attempt('a2','0002','r0002','c0003','update:0001')
    if not keep_legacy_graph:(run/'graph_snapshots/0001.json').unlink()
    second=m.commit_update(ROOT,run,'graph_snapshots/0001.json' if keep_legacy_graph else None,'0002','a2')
    target=json.loads((run/second['snapshot']/'regions/r0002/region.json').read_text())
    assert target['controls']['c0003']['action_refs']==['a2']
    assert target['actions']['a2']['result']['exception']=='external_app'
    assert read_region(run,second)['transitions'][0]['target_region']=='r0002'


def test_duplicate_control_names_are_not_merged_or_guessed(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    g['controls'][1]['proposal']['text']='Policy'
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    with pytest.raises(ValueError,match='ambiguous'):invoke(m,run)
    assert not (run/'knowledge_current.json').exists()


def test_region_rename_keeps_changes_bound_to_old_identity(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    r['action_result']['exception']='none'
    r['previous_regions'][0]['state']='changed_interactive'
    r['regions']=[{'name':'Renamed menu','previous_name':'Menu','parent_index':None,'description':'renamed','reason':'changed','bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(r))
    p=invoke(m,run);region=read_region(run,p)
    assert region['name']=='Renamed menu'
    assert region['actions']['a1']['region_changes'][0]['region']=='r1'
    assert region['transitions']==[]  # Renaming/local change is not navigation.


def test_compact_region_has_no_boxes_history_or_exploration_and_derives_progress(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    g['controls'][0]['proposal']['bbox']={'left':1,'top':2,'right':10,'bottom':20}
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    p=invoke(m,run);region=read_region(run,p)
    assert not ({'history','exploration'} & region.keys())
    assert 'bbox' not in json.dumps(region)
    q=m.sibling('stepwise_flow').assemble_current_context(ROOT,run,'r1')
    assert q['progress']['controls_without_record']==1
    assert q['progress']['controls_with_unresolved_attempts']==1
    assert 'completion' not in q['progress']


def test_recovery_update_uses_common_registration_without_control_or_graph_edge(tmp_path):
    m=module();run,g,r=fixture(tmp_path);invoke(m,run)
    action=run/'action_attempts/a2';action.mkdir()
    for name in ('before.png','after.png'):(action/name).write_bytes(b'no crop requested')
    (action/'receipt.json').write_text('{"exit_code":0}')
    (action/'dispatch.json').write_text(json.dumps({'recovery':{'working_region':'r1','trigger_attempt':'a1'},
        'source_call':'choice','action':{'action':'back','issuer':'agent'}}))
    r['action_result']['exception']='none'
    r['regions']=[{'name':'Menu','previous_name':'Menu','parent_index':None,'description':'returned','reason':'back','bbox':None}]
    r['previous_regions'][0]['state']='changed_interactive'
    r['exploration_update']['entry_name']='系统返回'
    (run/'calls/0002').mkdir();(run/'calls/0002/response.json').write_text(json.dumps(r))
    before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='recovery actions must not'):
        m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')
    assert (run/'knowledge_current.json').read_bytes()==before


def test_context_discloses_recovery_arrival_without_inventing_control_action(tmp_path):
    m=module();run,g,r=fixture(tmp_path);p=invoke(m,run)
    base=run/p['snapshot'];state=json.loads((base/'runtime_state.json').read_text())
    state.update(interactive_regions=['r1'],next_action_mode='explore',recovery='recovery.json')
    (base/'runtime_state.json').write_text(json.dumps(state))
    (base/'recovery.json').write_text(json.dumps({'actions':[{'operation':'back','result':{'description':'returned to Menu'},'evidence':{'after_observation':'o2'}}]}))
    q=m.sibling('stepwise_flow').assemble_current_context(ROOT,run,'r1')
    assert 'returned to Menu' not in q['user_prompt']
    assert q['stage']=='task_proposal'
    assert '恢复动作：back' not in q['user_prompt']


def test_ordinary_back_is_region_owned_and_records_only_actual_return(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    r['action_result']['exception']='none'
    r['previous_regions'][0]['state']='retained_interactive'
    r['regions']=[{'name':'Menu','previous_name':'Menu','parent_index':None,'description':'menu','reason':'visible','bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(r));invoke(m,run)
    a=run/'action_attempts/a2';a.mkdir()
    for n in ('before.png','after.png'):(a/n).write_bytes(b'no crop')
    (a/'binding.json').write_text(json.dumps({'status':'matched','region_ref':'r1','control_ref':None,'working_region':'r1','return_to':'r1','observation_ref':'o2'}))
    (a/'dispatch.json').write_text(json.dumps({'source_region':'r1','source_control':None,'source_call':'choice','action':{'action':'back','reason':'return'}}))
    (a/'receipt.json').write_text('{"exit_code":0}')
    call=run/'calls/0002';call.mkdir()
    r['regions']=[{'name':'Main','previous_name':'','parent_index':None,'description':'main','reason':'returned','bbox':None}]
    r['previous_regions'][0]['state']='not_visible'
    r['exploration_update']['entry_name']='系统返回'
    (call/'response.json').write_text(json.dumps(r));(call/'request.json').write_text(json.dumps({'screenshots':['action_attempts/a2/before.png','action_attempts/a2/after.png']}))
    pointer=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')
    owner=read_region(run,pointer)
    assert owner['actions']['a2']['control'] is None
    assert owner['actions']['a2']['operation']=='back'
    assert all('a2' not in c['action_refs'] for c in owner['controls'].values())
    assert any(e['attempt']=='a2' and e['source_control'] is None for e in owner['transitions'])
    assert m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')==pointer


def test_parameter_update_keeps_task_owner_separate_from_action_owner(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    r['action_result']['exception']='none'
    r['regions']=[{'name':'Parameter editor','previous_name':'','parent_index':None,'description':'editor','reason':'opened','bbox':None}]
    r['controls']=[{'text':'Value','previous_name':'','region_index':0,'icon_appearance':'','state':'visible','possible_operation':'input','uncertainty':'','bbox':None,'icon_bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(r));pointer=invoke(m,run)
    ownerfile=run/pointer['snapshot']/'regions/r1/region.json';owner=json.loads(ownerfile.read_text())
    owner['tasks']={'了解标签':{'name':'了解标签','control':'c1','task_type':'parameter','action':'tap','handling':'explore','reason':'了解标签输入','equivalent_to':'','status':'pending','attempts':[]}}
    ownerfile.write_text(json.dumps(owner))
    folder=run/'action_attempts/a2';folder.mkdir()
    for n in ['before.png','after.png']:(folder/n).write_bytes(b'no crop')
    (folder/'binding.json').write_text(json.dumps({'status':'matched','region_ref':'r0002','control_ref':'c0003','working_region':'r1','task_region':'r1','task_name':'了解标签','observation_ref':'o2'}))
    (folder/'dispatch.json').write_text(json.dumps({'source_region':'r0002','source_control':'c0003','source_call':'selection','action':{'action':'input_text','text':'Breakfast'}}))
    (folder/'receipt.json').write_text('{"exit_code":0}')
    call=run/'calls/0002';call.mkdir()
    r['regions'][0]['previous_name']='Parameter editor'
    r['controls'][0]['previous_name']='Value'
    r['previous_regions']=[{'name':'Parameter editor','state':'changed_interactive','evidence':'value changed'}]
    r['exploration_update']['entry_name']='Value'
    r['task_result']={'name':'了解标签','status':'done','evidence':'文本字段接受输入','findings':[{'name':'标签','description':'自由文本输入','domain':{'type':'text','values':[],'min':None,'max':None},'conditions':[],'evidence':'before/after input'}]}
    r['action_result']['recovery_handoff']=''
    for c in r['controls']:c.update(name=c['previous_name'],list_group='')
    r.pop('working_context',None)
    for region in r['regions']:region['task_review_reason']=''
    request=m.sibling('result_updater').build_update_request(ROOT,{'本轮探索任务':'了解标签'},['action_attempts/a2/before.png','action_attempts/a2/after.png'])
    (call/'request.json').write_text(json.dumps(request));(call/'response.schema.json').write_text(json.dumps(request['response_schema']));(call/'response.json').write_text(json.dumps(r))
    pointer=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')
    owner=read_region(run,pointer);child=json.loads((run/pointer['snapshot']/'regions/r0002/region.json').read_text())
    assert owner['tasks']['了解标签']['status']=='done'
    assert 'a2' not in owner['actions'] and child['actions']['a2']['control']=='c0003'
    assert owner['tasks']['了解标签']['findings']['标签']['source']['region']=='r0002'


def test_region_owned_scroll_uses_binding_not_result_label(tmp_path):
    m=module();run,g,r=fixture(tmp_path)
    r['action_result']['exception']='none'
    r['previous_regions'][0]['state']='retained_interactive'
    r['regions']=[{'name':'Menu','previous_name':'Menu','parent_index':None,'description':'menu','reason':'visible','bbox':None}]
    (run/'calls/0001/response.json').write_text(json.dumps(r));invoke(m,run)
    a=run/'action_attempts/a2';a.mkdir()
    for n in ('before.png','after.png'):(a/n).write_bytes(b'no crop')
    (a/'binding.json').write_text(json.dumps({'status':'matched','region_ref':'r1','control_ref':None,'working_region':'r1','return_to':'r1','observation_ref':'o2'}))
    (a/'dispatch.json').write_text(json.dumps({'source_region':'r1','source_control':None,'source_call':'choice','action':{'action':'scroll','reason':'return'}}))
    (a/'receipt.json').write_text('{"exit_code":0}')
    call=run/'calls/0002';call.mkdir()
    r['regions']=[{'name':'Main','previous_name':'','parent_index':None,'description':'main','reason':'returned','bbox':None}]
    r['previous_regions'][0]['state']='not_visible'
    r['exploration_update']['entry_name']='描述性的列表名称'
    (call/'response.json').write_text(json.dumps(r));(call/'request.json').write_text(json.dumps({'screenshots':['action_attempts/a2/before.png','action_attempts/a2/after.png']}))
    pointer=m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')
    owner=read_region(run,pointer)
    assert owner['actions']['a2']['control'] is None
    assert owner['actions']['a2']['operation']=='scroll'
    assert all('a2' not in c['action_refs'] for c in owner['controls'].values())
    assert any(e['attempt']=='a2' and e['source_control'] is None for e in owner['transitions'])
    assert m.commit_update(ROOT,run,'graph_snapshots/0001.json','0002','a2')==pointer


@pytest.mark.parametrize('resolved',[False,True])
def test_unassociated_coordinate_click_keeps_evidence_without_wrong_control(tmp_path,resolved):
    m=module();run,g,r=fixture(tmp_path);g['action_edges']=[]
    (run/'graph_snapshots/0001.json').write_text(json.dumps(g))
    association={'status':'unconfirmed','target':'outside blank','x':90,'y':90,'candidates':[]}
    (run/'action_attempts/a1/binding.json').write_text(json.dumps({'status':'matched','region_ref':'r1','control_ref':None,'observation_ref':'o1','association':association}))
    (run/'action_attempts/a1/dispatch.json').write_text(json.dumps({'source_region':'r1','source_control':None,'source_call':'choice','action':{'action':'click','target':'outside blank','x':90,'y':90}}))
    (run/'calls/0001/request.json').write_text(json.dumps({'screenshots':['before.png','after.png']}))
    for name in ['before.png','after.png']:(run/name).write_bytes(b'evidence reference only')
    if resolved:
        from PIL import Image
        for name in ['before.png','after.png']:Image.new('RGB',(200,200),'white').save(run/name)
        r['action_result']['exception']='none'
        r['regions']=[{'name':'Menu','previous_name':'Menu','parent_index':None,'description':'menu','reason':'visible','bbox':None}]
        r['previous_regions'][0]['state']='changed_interactive'
        r['controls']=[{'text':'outside blank','previous_name':'','region_index':0,'icon_appearance':'','state':'visible','possible_operation':'close','uncertainty':'','bbox':{'left':70,'top':70,'right':110,'bottom':110},'icon_bbox':None}]
        (run/'calls/0001/response.json').write_text(json.dumps(r))
    p=invoke(m,run);region=read_region(run,p)
    if resolved:
        cid=region['actions']['a1']['control']
        assert cid and region['controls'][cid]['name']=='outside blank'
        assert region['actions']['a1']['association']['status']=='confirmed_by_update'
        assert region['controls'][cid]['action_refs']==['a1']
        return
    assert region['actions']['a1']['control'] is None
    assert region['actions']['a1']['association']==association
    assert all(not c['action_refs'] for c in region['controls'].values())
