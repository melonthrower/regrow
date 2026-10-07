"""Incremental local batches and cross-owner foreground identities."""
from copy import deepcopy
import json
import pytest
from tests.test_region_function_inventory import alarm_region, module, reply, ROOT
from tests.test_stepwise_region_tasks import tasks, proposal, row
from tests.test_stepwise_resume_route import fixture


def test_new_five_task_batch_summarizes_only_after_all_five_finish():
    _,region,_=alarm_region();m=module();m.register(region,reply(),'first')
    old=deepcopy(region['functions']);records={region['id']:region};state={'working_region':region['id']}
    cid=next(iter(region['controls']))
    for i in range(5):
        region['tasks']['new-'+str(i)]={**deepcopy(region['tasks'][cid]),'status':'pending','knowledge':''}
    for i in range(5):
        assert m.next_ready(records,state) is None
        assert region['functions']==old
        region['tasks']['new-'+str(i)]['status']='done'
        region['tasks']['new-'+str(i)]['knowledge']='new fact '+str(i)
    assert m.next_ready(records,state)==region['id']
    m.register(region,reply(),'second',records)
    assert m.next_ready(records,state) is None


def test_new_control_needs_inventory_before_summary_even_without_pending_tasks():
    _,region,_=alarm_region();m=module();m.register(region,reply(),'first')
    region['controls']['new']={'name':'new control','observations':[]}
    assert not m.ready(region)
    region['task_inventory']['controls'].append('new')
    region['task_inventory']['review']={'reason':'new operation'}
    assert not m.ready(region)


@pytest.mark.parametrize("handling,status", [("record","record_only"),("explore","done")])
def test_known_exit_and_reworded_observation_do_not_repeat_summary(handling,status):
    _,region,_=alarm_region();m=module()
    cid=next(iter(region['controls']))
    region['tasks'][cid]['handling']=handling;region['tasks'][cid]['status']=status
    region['tasks'][cid]['knowledge']='关闭当前列表'
    m.register(region,reply(),'first')
    before=m.signature(region)
    region['actions']['exit']={'control':cid,'operation':'click','delivery':'executed_receipt_zero',
        'result':{'description':'列表关闭','exception':'none'},'interactive_regions':['parent']}
    region['transitions'].append({'attempt':'exit','source_control':cid,'target_region':'parent'})
    region['controls'][cid]['observations'].append({'possible_operation':'退出列表','state':'closed'})
    assert m.signature(region)==before and m.review_current(region)
    assert any(a['动作记录']=='exit' for a in m.action_results(region))


def test_adopted_foreign_support_waits_for_its_whole_new_batch():
    from tests.test_function_scope import linked
    owner,child,records=linked();m=module();value=reply();value['functions'][0]['tasks'].append('picker / 周期')
    m.register(owner,value,'first',records)
    child['tasks']['周期']['reason']='changed condition'
    child['tasks']['标签']['status']='pending'
    assert not m.ready(owner,records)
    child['tasks']['标签']['status']='done'
    assert m.ready(owner,records) and not m.review_current(owner,records)


def test_task_registration_is_local_even_for_same_named_controls():
    _,records,_=fixture();m=tasks();owner=records['menu'];other=records['main']
    other['controls']['open']['name']=owner['controls']['open']['name']
    before=deepcopy(other)
    m.apply_plan(owner,proposal([row(handling='record')]),'local',records=records)
    assert other==before and owner['tasks']['查看内容']['control']=='open'
    other['controls']['foreign']={'name':'foreign control'}
    bad=proposal([row(control='foreign control')]);bad['inventory']='partial'
    with pytest.raises(ValueError,match='本区块'):m.apply_plan(owner,bad,'foreign',records=records)


def test_related_trigger_keeps_owner_without_promoting_background(tmp_path):
    import numpy as np
    from PIL import Image
    import action_candidates, action_binding
    flow,records,state=fixture();state.update(interactive_regions=['menu'],working_region='main')
    records['menu']['reached_by']=[{'source_region':'main','source_control':'open','attempt':'a3'}]
    records['main']['controls']['unrelated']=deepcopy(records['main']['controls']['open'])
    records['main']['controls']['unrelated']['name']='Unrelated background button'
    frame=tmp_path/'screen.png';crop=tmp_path/'trigger.png'
    pixels=np.random.default_rng(40).integers(0,256,(160,160,3),dtype=np.uint8)
    Image.fromarray(pixels).save(frame);Image.fromarray(pixels[10:40,10:40]).save(crop)
    records['main']['controls']['open']['observations'][0]['image']=str(crop)
    state['observation']['image']=str(frame)
    q=flow.assemble_context(ROOT,records,state,'main');before=deepcopy((records,state))
    action_candidates.attach_related(q,records,state)
    assert [(c['region_ref'],c['id']) for c in q['backend_candidates']]==[('menu','open'),('main','open')]
    binding=action_binding.bind_action_target(q,{'target':'打开主体','action':'click','x':25,'y':25})
    assert (binding['region_ref'],binding['control_ref'])==('main','open')
    assert (records,state)==before and state['interactive_regions']==['menu']


def test_related_owner_provenance_does_not_claim_whole_owner_interactive(tmp_path):
    from tests.test_action_source_observation import source,write,m
    source(tmp_path)
    request=json.loads((tmp_path/'calls/0001/request.json').read_text())
    request['backend_candidates']=[{'region_ref':'outer','id':'trigger','candidate_scope':'foreground_entry_trigger'}]
    write(tmp_path/'calls/0001/request.json',request)
    value=m.action_source_observation(tmp_path,'0001','obs-old','outer','trigger')
    assert value['region_refs']==['actual-source'] and value['related_control']['control']=='trigger'
    with pytest.raises(ValueError):m.action_source_observation(tmp_path,'0001','obs-old','outer','other')


def test_prior_summary_stays_readable_until_new_batch_finishes():
    import function_scope
    _,region,_=alarm_region();m=module();m.register(region,reply(),'first')
    region['tasks']['时间']['status']='pending'
    view=function_scope.disclose({region['id']:region},region['id'])
    assert view['self']['status']=='needs_review' and view['self']['summary']
    assert view['knowledge'] and view['functions']


def test_corrected_registered_knowledge_invalidates_prior_summary():
    _,region,_=alarm_region();m=module();cid=next(iter(region['controls']))
    task=region['tasks'][cid];task.update(handling='record',status='record_only',knowledge='关闭列表')
    m.register(region,reply(),'first')
    task['knowledge']='展开状态下收起列表；收起状态下打开列表'
    assert not m.review_current(region) and m.ready(region)


def test_related_trigger_uses_admitted_icon_with_recorded_click_area(tmp_path):
    import numpy as np
    from PIL import Image
    import action_candidates,visual_choices
    pixels=np.random.default_rng(51).integers(0,256,(100,100,3),dtype=np.uint8)
    source=tmp_path/'source.png';icon=tmp_path/'icon.png';button=tmp_path/'button.png'
    Image.fromarray(pixels).save(source);Image.fromarray(pixels[25:35,25:35]).save(icon)
    Image.fromarray(pixels[20:40,20:40]).save(button)
    bbox=dict(zip(('left','top','right','bottom'),(20,20,40,40)))
    row={'image':str(button),'icon_image':str(icon),'source_image':str(source),
         'bbox':bbox,'click_bbox':bbox,'image_quality':'clear','icon_quality':'clear',
         'image_quality_reason':'observed clear'}
    item={'image':str(button),'image_quality':'clear','image_quality_reason':'observed clear'}
    action_candidates.use_recorded_icon(item,{'observations':[row]})
    assert item['image']==str(icon) and item['click_bbox']==bbox
    assert visual_choices.match_control(item,str(source))['box']==[20,20,40,40]
    row['icon_quality']='uncertain';untouched={'image':str(button)}
    action_candidates.use_recorded_icon(untouched,{'observations':[row]})
    assert untouched=={'image':str(button)}
