from pathlib import Path
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT

def test_unused_action_arguments_are_normalized():
    m=tasks().helper('action_commands')
    p={'action':'click','target':'button','x':10,'y':20,'reason':'test','text':'ignored','end_x':9,'end_y':8}
    m.validate(p)
    assert m.normalize(p)['text'] is None and m.normalize(p)['end_x'] is None

def test_update_does_not_ask_model_for_framework_working_region():
    q=tasks().helper('update_step').build_update_request(ROOT,{},['a','b'])
    assert 'working_context' not in q['response_schema']['properties']

def test_back_needs_no_display_label_or_prepermission():
    q={'source':{'region':'r','observation':'o'}}
    p={'action':'back','target':'返回上一层','x':None,'y':None}
    assert tasks().helper('stepwise_flow').bind_action_target(q,p)['status']=='matched'

def test_markor_low_score_does_not_refute_model_position(monkeypatch,tmp_path):
    from PIL import Image
    m=tasks().helper('stepwise_flow');frame=tmp_path/'f.png';Image.new('RGB',(1080,2340),'white').save(frame)
    crop=tmp_path/'crop.png';Image.new('RGB',(53,42),'black').save(crop)
    q={'source':{'region':'r','observation':'o'},'image_refs':[str(frame)],'backend_candidates':[{'id':'c','name':'文件夹工具栏入口','image':str(crop)}]}
    # Actual matcher gives a low-confidence candidate for this synthetic crop.
    import importlib.util
    original=importlib.util.module_from_spec
    def inject(spec):
        mod=original(spec)
        if spec.name=='stepwise_image_match':
            loader=spec.loader.exec_module
            def execute(m):
                loader(m);m.locate=lambda *a:{'accepted':False,'box':[665,191,718,233],'score':0.60,'candidates':[]}
            spec.loader.exec_module=execute
        return mod
    monkeypatch.setattr(importlib.util,'module_from_spec',inject)
    p={'action':'click','target':'文件夹工具栏入口','x':692,'y':212,'reason':'当前顶部白色文件夹图标'}
    assert m.bind_action_target(q,p)['status']=='matched'
    p['x']=900
    assert m.bind_action_target(q,p)['status']=='unresolved'


def test_control_description_revision_preserves_identity(tmp_path):
    from tests.test_stepwise_task_correction import saved
    run,q,_=saved(tmp_path);m=tasks().helper('repair_stages')
    _,records,_=tasks().helper('discovery_step').load(run)
    r=records['r1'];cid=next(iter(r['controls']));c=r['controls'][cid]
    job={'stage':'task_proposal','request':q,'call':'description','supplements':[]}
    m.edit_record(ROOT,run,job,{'region':r['name'],'control':c['name'],'field':'description','before':'','after':'顶部白色图标','evidence':'当前图'})
    updated=tasks().helper('discovery_step').load(run)[1]['r1']['controls'][cid]
    assert updated['description']=='顶部白色图标' and updated['name']==c['name']
