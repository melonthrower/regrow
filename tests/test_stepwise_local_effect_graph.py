import json
from tests.test_stepwise_region_graph import seed
from tests.test_region_registration import fixture,module,invoke,read_region


def test_local_effect_is_not_a_graph_route_but_action_remains(tmp_path,monkeypatch):
    graph,base,r,save=seed(tmp_path,monkeypatch)
    r['actions']['a1']['interactive_regions']=['a','b']
    r['transitions'].append({'source_control':'c','target_region':'a','attempt':'a1'})
    save(base/'regions/a/region.json',r)
    out=graph.project(tmp_path)
    assert [(e['source'],e['target']) for e in out['edges']]==[('a','b')]
    assert len(out['nodes'][0]['controls'][0]['actions'])==1


def test_update_keeps_same_region_change_without_navigation_edge(tmp_path):
    run,_,reply=fixture(tmp_path)
    reply['action_result'].update(exception='none',description='value changed within Menu')
    reply['previous_regions'][0]['state']='changed_interactive'
    (run/'calls/0001/response.json').write_text(json.dumps(reply))
    r=read_region(run,invoke(module(),run))
    assert r['transitions']==[] and r['reached_by']==[]
    assert r['actions']['a1']['result']['description']=='value changed within Menu'
    assert r['actions']['a1']['region_changes'][0]['state']=='changed_interactive'


def test_input_history_does_not_require_self_transition(tmp_path,monkeypatch):
    from tests.test_stepwise_resume_route import ROOT
    monkeypatch.syspath_prepend(str(ROOT));import input_target
    obs={'image':'old.png','evidence':{'observation':'o'}}
    click={'control':'open','operation':'click','delivery':'executed_receipt_zero','result':{'exception':'none'},'interactive_regions':['r'],'region_changes':[{'region':'r','state':'changed_interactive'}]}
    text={'control':'field','operation':'input_text','delivery':'executed_receipt_zero','text_delivered':True,'result':{'exception':'none'},'evidence':{'before_image':'before.png','before_observation':'o'}}
    r={'observations':[obs],'controls':{c:{'name':c,'observations':[obs]} for c in ['open','field']},'actions':{'click':click,'text':text},'transitions':[],'tasks':{'input':{'status':'done','attempts':['text']}}}
    args=(tmp_path,{'r':r},{'region_ref':'r','control_ref':'open','observation_ref':'o'},{'image_refs':['current.png']})
    assert input_target.context(*args)['targets'][0]['control']=='field'
    click['delivery']='unconfirmed'
    assert input_target.context(*args)['targets']==[]
