from copy import deepcopy
import json
import numpy as np
from PIL import Image
from tests.test_stepwise_update_region_matching import case
from tests.test_recovery_discovery import mod,seeded_run,discovery_reply,ROOT


def control_case(tmp_path):
    m,records,reply=case(tmp_path)
    with Image.open(tmp_path/'region.png') as image:pixels=np.array(image)
    region=records['r0001'];region['observations'][0].update(controls_complete=True,evidence={'source_call':'old'})
    region['controls']={};reply['controls']=[];reply['regions'][0]['controls_complete']=True
    for i,(name,t,b) in enumerate([('Settings',10,30),('Help',45,65)]):
        path=tmp_path/f'control{i}.png';Image.fromarray(pixels[t:b,10:80]).save(path)
        region['controls'][f'c{i}']={'name':name,'observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','text':name,'icon_description':'','image':str(path),'evidence':{'source_call':'old'}}]}
        reply['controls'].append({'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','name':name,'text':name,'icon_appearance':'','region_index':0,'previous_name':'',
            'bbox':{'left':180,'top':140+t,'right':250,'bottom':140+b}})
    with Image.open(tmp_path/'after.png') as image:frame=np.array(image)
    frame[141,171]=255-frame[141,171] # region not pixel-identical; control identities unchanged
    Image.fromarray(frame).save(tmp_path/'after.png')
    return m,records,reply


def test_complete_controls_do_not_override_model_decision(tmp_path):
    m,records,reply=control_case(tmp_path)
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized == reply and not audit


def test_partial_or_unverified_inventory_cannot_auto_merge(tmp_path):
    m,records,reply=control_case(tmp_path)
    for which in ['new','old','subset','layout']:
        rs=deepcopy(records);p=deepcopy(reply)
        if which=='new':p['regions'][0]['controls_complete']=False
        if which=='old':rs['r0001']['observations'][0].pop('controls_complete')
        if which=='subset':p['controls'].pop()
        if which=='layout':p['controls'][0]['bbox']['top']+=35;p['controls'][0]['bbox']['bottom']+=35
        normalized,audit=m.normalize(rs,tmp_path,tmp_path/'after.png',p)
        assert not audit and normalized==p,which


def test_same_control_names_without_region_appearance_do_not_merge(tmp_path):
    m,records,reply=control_case(tmp_path)
    Image.new('RGB',(300,260),'white').save(tmp_path/'after.png')
    normalized,audit=m.normalize(records,tmp_path,tmp_path/'after.png',reply)
    assert normalized==reply and not audit


def test_discovery_registration_preserves_explicit_new_identity(tmp_path):
    m=mod('discovery_step');run=seeded_run(tmp_path);m.await_discovery(run,'returned.png','return')
    q=m.request_from_run(ROOT,run);reply=discovery_reply()
    reply['regions'][0].update(name='另一背景的菜单',identity='new',previous_name='',context_matches=None)
    reply['foreground'].update(interactive_areas=[{'bbox':reply['regions'][0]['bbox'],'reason':'fixture'}],excluded_areas=[])
    reply['regions'][0].update(task_review_reason='',controls_complete=True,out_of_scope_reason='')
    for c in reply['controls']:
        c.update(name=c['text'],identity='new',previous_name='')
    reply['controls']=[]  # Relocation identifies Regions before local control scanning.
    folder=run/'calls/0003';folder.mkdir()
    (folder/'request.json').write_text(json.dumps(q));(folder/'response.json').write_text(json.dumps(reply))
    before=m.load(run)[1];m.commit(ROOT,run,'0003');_,after,state=m.load(run)
    assert len(after)==len(before)+1
    assert set(after['r1']['controls'])==set(before['r1']['controls'])
    assert state['interactive_regions']!=['r1']
    assert json.loads((folder/'response.json').read_text())==reply


def test_both_prompts_explain_completeness_and_schema(tmp_path):
    discovery=mod('discovery_step');run=seeded_run(tmp_path);discovery.await_discovery(run,'returned.png','return')
    q=discovery.request_from_run(ROOT,run)
    u=mod('update_step').build_update_request(ROOT,{},[])
    for request in (q,u):
        assert 'controls_complete' in request['response_schema']['properties']['regions']['items']['properties']
        assert '局部批次' in request['system_prompt'] and '确定、取消' in request['system_prompt']
