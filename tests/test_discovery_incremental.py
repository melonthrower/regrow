"""Incremental observation must retain confirmed facts without guessing missing identity."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module(name='discovery_completion'):
    s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_recall_only_relevant_history_and_keep_duplicate_names():
    m=module();records={f'r{i}':{'name':f'Unrelated folder {i}','description':'folder picker','controls':{}} for i in range(60)}
    records['a']={'name':'VS Code status bar','description':'bottom line and cell position','controls':{}}
    records['b']={'name':'VS Code status bar','description':'status information on second window','controls':{}}
    hits=m.retrieve(records,[{'name':'VS Code status bar','description':'bottom status information'}])
    assert set(hits)=={'a','b'}
    assert m.retrieve(records,[{'name':'音量设置','description':'音量滑块'}])==[]

def test_partition_keeps_confirmed_and_holds_dependent_children():
    m=module();reply={'regions':[
        {'name':'Menu','identity':'same','previous_name':'Menu','parent_index':None},
        {'name':'Unknown','identity':'uncertain','previous_name':None,'parent_index':None},
        {'name':'Child','identity':'new','previous_name':None,'parent_index':1}],
        'controls':[{'name':'Open','identity':'new','previous_name':None,'region_index':0},
                    {'name':'Child control','identity':'new','previous_name':None,'region_index':2}]}
    old=deepcopy(reply);accepted,gaps=m.partition(reply)
    assert [r['name'] for r in accepted['regions']]==['Menu']
    assert [c['name'] for c in accepted['controls']]==['Open']
    assert len(gaps)==3 and reply==old

def test_missing_reply_cannot_silently_close_gap():
    m=module()
    with pytest.raises(ValueError,match='缺口'):
        m.resolve_gaps([{'item':'状态栏'}],[],{'regions':[],'controls':[]})


def seed(tmp_path):
    import locator
    from PIL import Image
    m=module('discovery_step');flow=module('stepwise_flow');run=tmp_path/'run'
    snap=run/'knowledge_snapshots/seed';snap.mkdir(parents=True)
    Image.new('RGB',(100,100),'white').save(run/'frame.png')
    records={k:flow.new_region(k,name,name) for k,name in [('r0001','Toolbar'),('r0002','Status bar')]}
    for rid,r in records.items():
        p=snap/'regions'/rid;p.mkdir(parents=True);(p/'region.json').write_text(json.dumps(r))
    (run/'knowledge_current.json').write_text(json.dumps({'snapshot':'knowledge_snapshots/seed'}))
    (snap/'source.json').write_text('{}')
    (snap/'runtime_state.json').write_text(json.dumps({'next_action_mode':'discover','pending_frame':'frame.png','working_region':'r0001','interactive_regions':[]}))
    q={'role':'observation','system_prompt':'Observe','user_prompt':'{}','screenshots':[str(run/'frame.png')],
       'response_schema':locator.schema(ROOT,'relocate'),
       'discovery_context':{'mode':'relocate','focus':'r0001','region_names':{'Toolbar':'r0001'},'control_names':{},'visual_plan':{'mode':'relocate','focus':'r0001','regions':[]}}}
    def region(name,identity):return {'name':name,'description':name,'reason':'visible','parent_index':None,'bbox':None,'identity':identity,'previous_name':name if identity=='same' else None,'identity_evidence':'visible appearance','controls_complete':False}
    reply={'foreground':{'description':'editor','evidence':'image','uncertainty':''},'focus_presence':'interactive','regions':[region('Toolbar','same'),region('Status bar','uncertain')],'controls':[],'excluded':[],'uncertainties':[]}
    return m,run,q,reply

def save_call(run,ref,q,reply):
    p=run/'calls'/ref;p.mkdir(parents=True)
    (p/'request.json').write_text(json.dumps(q));(p/'response.json').write_text(json.dumps(reply))

def test_actual_partial_commit_and_followup_preserve_foreground_and_provenance(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);save_call(run,'0001',q,reply)
    m.commit(ROOT,run,'0001');_,r,s=m.load(run)
    assert len(r['r0001']['observations'])==1 and not r['r0002']['observations']
    assert s['next_action_mode']=='discover' and s['interactive_regions']==[]
    nextq=locator.request_from_run(ROOT,run);prompt=json.loads(nextq['user_prompt'])
    assert prompt['已实际登记'][0]['区块']=='Toolbar'
    assert [x['名称'] for x in prompt['相关历史候选']]==['Status bar']
    nextreply=deepcopy(reply);nextreply['regions']=[nextreply['regions'][1]]
    nextreply['regions'][0].update(identity='same',previous_name='Status bar')
    nextreply['completion_updates']=[{'item':prompt['待补事项'][0]['item'],'resolution':'registered','region_index':0,'control_index':None,'evidence':'same bottom bar'}]
    save_call(run,'0002',nextq,nextreply);m.commit(ROOT,run,'0002');_,r,s=m.load(run)
    assert s['interactive_regions']==['r0001','r0002']
    assert len(r['r0001']['observations'])==1 and len(r['r0002']['observations'])==1
    before=(run/'knowledge_current.json').read_bytes();m.commit(ROOT,run,'0001')
    assert before==(run/'knowledge_current.json').read_bytes()
    assert not s['discovery_completion']['pending']

def test_changed_frame_and_empty_followup_leave_partial_intact(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    nextq=locator.request_from_run(ROOT,run);empty=deepcopy(reply);empty.update(regions=[],controls=[],completion_updates=[])
    save_call(run,'0002',nextq,empty);before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='缺口'):m.commit(ROOT,run,'0002')
    assert before==(run/'knowledge_current.json').read_bytes()
    from PIL import Image
    Image.new('RGB',(100,100),'black').save(run/'frame.png')
    with pytest.raises(ValueError,match='截图'):locator.request_from_run(ROOT,run)


def control(name,identity):
    return {'name':name,'text':name,'list_group':'','region_index':0,'identity':identity,'previous_name':name if identity=='same' else None,'identity_evidence':'appearance','icon_appearance':'','state':'visible','possible_operation':'tap','uncertainty':'','bbox':None,'icon_bbox':None,'click_bbox':None}

def test_local_completion_references_parent_without_overwriting_or_losing_controls(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path)
    q['discovery_context'].update(mode='local');q['discovery_context']['visual_plan']['next_offset']=8
    q['response_schema']=locator.schema(ROOT,'local');reply['regions']=reply['regions'][:1]
    reply['controls']=[control('Open','new'),control('Close','uncertain')]
    save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    _,r,s=m.load(run);old=deepcopy(r['r0001']);assert s.get('control_scan') is None
    nextq=locator.request_from_run(ROOT,run);prompt=json.loads(nextq['user_prompt'])
    out=deepcopy(reply);out['regions'][0]['description']='context reference must not overwrite'
    out['controls']=[control('Close','new')]
    out['completion_updates']=[{'item':prompt['待补事项'][0]['item'],'resolution':'registered','region_index':None,'control_index':0,'evidence':'visible Close button'}]
    save_call(run,'0002',nextq,out);m.commit(ROOT,run,'0002');_,r,s=m.load(run)
    assert r['r0001']['description']==old['description'] and r['r0001']['observations']==old['observations']
    assert len(r['r0001']['controls'])==2 and len(s['observation']['control_refs'])==2
    assert all(c['observations'][-1]['evidence']['observation']==s['observation']['id'] for c in r['r0001']['controls'].values())
    assert s['control_scan']['r0001']==8


def test_cross_batch_duplicate_region_rejected_and_original_source_index_retained(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);reply['regions'].reverse()
    save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    _,r,s=m.load(run);assert r['r0001']['observations'][-1]['evidence']['source_field']=='/regions/1'
    nextq=locator.request_from_run(ROOT,run);prompt=json.loads(nextq['user_prompt'])
    bad=deepcopy(reply);bad['regions']=[bad['regions'][1]];bad['regions'][0].update(identity='new',previous_name=None)
    bad['completion_updates']=[{'item':prompt['待补事项'][0]['item'],'resolution':'unresolved','region_index':None,'control_index':None,'evidence':'still unsure'}]
    save_call(run,'0002',nextq,bad);before=(run/'knowledge_current.json').read_bytes()
    with pytest.raises(ValueError,match='已登记区块'):m.commit(ROOT,run,'0002')
    assert before==(run/'knowledge_current.json').read_bytes()


def test_repair_adapter_accepts_partial_without_consuming_correction(tmp_path):
    m,run,q,reply=seed(tmp_path);save_call(run,'0001',q,reply)
    result=module('repair_stages').accept(ROOT,run,{'stage':'discovery','request':q,'candidate':reply,'call':'0001'})
    assert result['snapshot'] and m.load(run)[2]['discovery_completion']['pending']


def test_cross_batch_list_group_representative_is_checked(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path)
    q['discovery_context'].update(mode='local');q['discovery_context']['visual_plan']['next_offset']=8
    q['response_schema']=locator.schema(ROOT,'local');reply['regions']=reply['regions'][:1]
    reply['controls']=[control('First row','new'),control('Search','uncertain')];reply['controls'][0]['list_group']='result'
    save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    nextq=locator.request_from_run(ROOT,run);prompt=json.loads(nextq['user_prompt'])
    bad=deepcopy(reply);bad['controls']=[control('Second row','new')];bad['controls'][0]['list_group']='result'
    bad['completion_updates']=[{'item':prompt['待补事项'][0]['item'],'resolution':'unresolved','region_index':None,'control_index':None,'evidence':'search unresolved'}]
    save_call(run,'0002',nextq,bad)
    with pytest.raises(ValueError,match='代表控件'):m.commit(ROOT,run,'0002')


def test_bad_indices_stay_in_standard_diagnostics(tmp_path):
    m,run,q,reply=seed(tmp_path);reply['regions'][0]['parent_index']=99;save_call(run,'0001',q,reply)
    with pytest.raises(ValueError,match='parent_region'):m.commit(ROOT,run,'0001')

def test_uncertain_only_followup_retains_gap_and_updates_reason(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    nextq=locator.request_from_run(ROOT,run);prompt=json.loads(nextq['user_prompt'])
    out=deepcopy(reply);out['regions']=out['regions'][1:];out['regions'][0]['description']='same item, identity still ambiguous'
    out['completion_updates']=[{'item':prompt['待补事项'][0]['item'],'resolution':'unresolved','region_index':0,'control_index':None,'evidence':'several similar old bars'}]
    save_call(run,'0002',nextq,out);m.commit(ROOT,run,'0002');_,r,s=m.load(run)
    assert len(s['discovery_completion']['pending'])==1
    assert s['discovery_completion']['pending'][0]['proposal']['description']=='same item, identity still ambiguous'
    assert s['next_action_mode']=='discover' and not s['interactive_regions']
    assert len(r['r0001']['observations'])==1

def test_global_supplement_has_no_unrelated_focus_controls(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001')
    snap,r,s=m.load(run);r['r0001']['controls']={f'c{i}':{'name':f'Unrelated {i}','observations':[]} for i in range(100)}
    module('register_update').write_json(snap/'regions/r0001/region.json',r['r0001'])
    nextq=locator.request_from_run(ROOT,run)
    assert json.loads(nextq['user_prompt'])['本区块控件身份候选']==[]


def test_new_same_named_gap_is_not_silently_dropped():
    m=module();pending=[{'item':'区块：Bar','kind':'region','index':0,'name':'Bar','proposal':{'name':'Bar'}}]
    reply={'regions':[{'name':'Bar','identity':'uncertain','previous_name':None,'parent_index':None}], 'controls':[],
           'completion_updates':[{'item':'区块：Bar','resolution':'unresolved','region_index':None,'control_index':None,'evidence':'original remains unresolved'}]}
    class Diagnostics:
        def collect(self,*a):return {'errors':[]}
        def check(self,*a):pass
    _,gaps,_,_=m.prepare_registration(reply,{}, {},{'pending':pending,'regions':[],'controls':[]},Diagnostics())
    assert len(gaps)==2 and len({g['item'] for g in gaps})==2


def test_supplement_upgrades_historical_inventory_required_flag():
    import locator
    schema=locator.schema(ROOT,'relocate')
    schema['properties']['regions']['items']['required']=[k for k in schema['properties']['regions']['items']['required'] if k!='controls_complete']
    module().extend_schema(schema)
    assert 'controls_complete' in schema['properties']['regions']['items']['required']


def test_resumed_supplement_uses_current_fixed_prompt_files(tmp_path):
    import locator
    m,run,q,reply=seed(tmp_path);q['system_prompt']='obsolete prefix'
    q['fixed_parts']=[{'path':'任务/当前区块重定位.prompt','text':'obsolete prefix'}]
    save_call(run,'0001',q,reply);m.commit(ROOT,run,'0001');nextq=locator.request_from_run(ROOT,run)
    assert 'obsolete prefix' not in nextq['system_prompt']
    assert nextq['system_prompt']=='\n\n'.join(p['text'] for p in nextq['fixed_parts'])
