from copy import deepcopy
import json
import pytest
from tests.test_recovery_discovery import mod, ROOT
from tests.test_stepwise_task_correction import saved, repair, Calls, answer


def test_collect_all_control_binding_errors():
    m=mod('registration_diagnostics')
    records={'r':{'name':'搜索','controls':{'c':{'name':'城市'}}}}
    q={'discovery_context':{'region_names':{'搜索':'r'},'control_names':{'城市':'c'}}}
    p={'regions':[{'name':'搜索','identity':'same','previous_name':'搜索'}], 'controls':[
        {'name':n,'region_index':0,'identity':'same','previous_name':n} for n in ['输入框','返回','清除']]}
    result=m.collect('discovery',q,p,records)
    assert len(result['errors'])==3
    assert result['errors'][0]['path']=='/controls/0/previous_name'
    assert result['errors'][0]['actual']=='输入框' and result['errors'][0]['expected']==['城市']


def test_new_control_conflict_blocks_duplicate_before_write():
    m=mod('registration_diagnostics')
    r={'r':{'name':'文件','controls':{'c':{'name':'搜索'}}}}
    q={'discovery_context':{'region_names':{'文件':'r'},'control_names':{}}}
    p={'regions':[{'name':'文件','identity':'same','previous_name':'文件'}], 'controls':[{'name':'搜索','region_index':0,'identity':'new','previous_name':''}]}
    assert any(e['code']=='existing_control_conflict' for e in m.collect('discovery',q,p,r)['errors'])


def test_combined_record_edit_and_proposal_is_atomic(tmp_path):
    run,q,good=saved(tmp_path);m=repair();d=mod('discovery_step')
    before=(run/'knowledge_current.json').read_bytes()
    edit={'region':'Menu','control':'Policy','field':'name','before':'Policy','after':'Privacy','evidence':'visible label'}
    bad=deepcopy(good);bad['operations'][0]['control']='unknown'
    response={**answer('revise',bad),'record_edit':edit}
    calls=Calls(run,[response]);ref,_=calls(m.request(ROOT,{'stage':'task_proposal','request':q,'history':[]},{}))
    job={'stage':'task_proposal','request':q,'call':ref,'candidate':bad,'record_edit':edit}
    with pytest.raises(ValueError):mod('repair_stages').accept(ROOT,run,job)
    assert (run/'knowledge_current.json').read_bytes()==before
    good=deepcopy(good)
    for op in good['operations']:
        if op['control']=='Policy':op['control']='Privacy'
    calls.replies=[{**answer('revise',good),'record_edit':edit}]
    ref,_=calls(m.request(ROOT,{'stage':'task_proposal','request':q,'history':[]},{}))
    job.update(call=ref,candidate=good)
    mod('repair_stages').accept(ROOT,run,job)
    assert d.load(run)[1]['r1']['controls']['c1']['name']=='Privacy'


def test_input_selects_all_before_text(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import action_commands as a, input_target
    from types import SimpleNamespace
    sent=[]
    t=SimpleNamespace(account={'gui_started':0,'max_gui_commands':4},save=lambda:None,screenshot=lambda p:p.write_bytes(b'x'),adb=lambda cmd:sent.append(cmd) or SimpleNamespace(returncode=0,stdout=b'',stderr=b''))
    monkeypatch.setattr(a.time,'sleep',lambda _:None)
    monkeypatch.setattr(input_target,'resolve',lambda *a:{'status':'same_target'})
    receipt=a.execute(t,{'action':'input_text','x':1,'y':2,'text':'wifi'},tmp_path,input_context={})
    assert sent[1]==['shell','input','keycombination','113','29']
    assert sent[2][2]=='text' and receipt['input_mode']=='replace'


def test_update_ignores_framework_working_label_and_reports_parameter_conflicts():
    m=mod('registration_diagnostics')
    old={'conditions':['old'],'domain':{'type':'enum'}}
    records={'r':{'name':'原工作区块','controls':{},'tasks':{'搜索':{'findings':{'输入':old,'反馈':old}}}}}
    p={'regions':[],'controls':[],'working_context':{'region_name':'当前区块','preserve_record':True},'task_result':{'findings':[{'name':n,'conditions':['new'],'domain':{'type':'enum'}} for n in ['输入','反馈']]}}
    report=m.collect('update',{},p,records,{'region_ref':'r','working_region':'r','task_name':'搜索'})
    assert report['errors']==[]
    p['task_result']['findings'][0]['domain']['type']='integer'
    report=m.collect('update',{},p,records,{'region_ref':'r','task_name':'搜索'})
    assert [e['code'] for e in report['errors']]==['parameter_fact_conflict']


def test_select_all_failure_does_not_type(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import action_commands as a, input_target
    from types import SimpleNamespace
    sent=[]
    def adb(cmd):
        sent.append(cmd)
        return SimpleNamespace(returncode=1 if cmd[2]=='keycombination' else 0,stdout=b'',stderr=b'')
    t=SimpleNamespace(account={'gui_started':0,'max_gui_commands':4},save=lambda:None,screenshot=lambda p:p.write_bytes(b'x'),adb=adb)
    monkeypatch.setattr(a.time,'sleep',lambda _:None)
    monkeypatch.setattr(input_target,'resolve',lambda *a:{'status':'same_target'})
    receipt=a.execute(t,{'action':'input_text','x':1,'y':2,'text':'wifi'},tmp_path,input_context={})
    assert len(sent)==2 and not receipt['text_delivered']


def test_same_proposal_with_different_record_repair_is_not_repetition(tmp_path):
    run,q,good=saved(tmp_path);m=repair()
    proposal=deepcopy(good)
    for op in proposal['operations']:
        if op['control']=='Policy':op['control']='Privacy'
    wrong={'region':'Menu','control':'Policy','field':'name','before':'Policy','after':'Wrong','evidence':'label'}
    right={**wrong,'after':'Privacy'}
    calls=Calls(run,[proposal,{**answer('revise',proposal),'record_edit':wrong},{**answer('revise',proposal),'record_edit':right}])
    result=m.Runner(ROOT,run,calls,None,lambda:6).perform('task_proposal',q)
    assert result['status']=='complete' and result['repairs']==2


def test_materialization_preserves_backend_resolved_identity():
    # Discovery resolved a display alias; downstream registration must retain that ID.
    records={'r':{'id':'r','name':'工具栏','controls':{'a':{'name':'搜索'},'b':{'name':'搜索'}}}}
    p={'regions':[{'name':'工具栏','previous_name':'工具栏','_matched_id':'r'}],
       'controls':[{'region_index':0,'name':'顶部搜索','previous_name':'搜索','_matched_id':'b'}]}
    report=mod('registration_diagnostics').collect('update',{},p,records)
    assert not report['errors']


def test_combined_merge_retains_original_request_aliases():
    old={'discovery_context':{'region_names':{'菜单':'r'},'control_names':{'按钮（候选1）':'old','按钮（候选2）':'keep'}}}
    new={'discovery_context':{'region_names':{'菜单':'r'},'control_names':{'按钮':'keep'}}}
    records={'r':{'controls':{'keep':{'merged_records':[{'id':'old'}]}}}}
    mod('repair_stages').preserve_repair_aliases(old,new,records)
    assert new['discovery_context']['control_names']=={'按钮':'keep','按钮（候选1）':'keep','按钮（候选2）':'keep'}


def test_function_wire_schema_omits_unsupported_unique_items():
    m=mod('region_functions')
    wire=m.wire_schema(ROOT)
    assert 'uniqueItems' not in json.dumps(wire)
    assert 'uniqueItems' in json.dumps(m.schema(ROOT))
