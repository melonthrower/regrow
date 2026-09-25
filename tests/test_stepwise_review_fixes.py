from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT
from tests.test_stepwise_deferral import setup


def test_preparation_repair_keeps_actual_control_and_task(tmp_path):
    run,q,d=setup(tmp_path)
    q.update(backend_candidates=[{'id':'c1','name':'Policy'}, {'id':'c2','name':'Settings'}])
    job={'stage':'action','request':q,'candidate':{'action':'click','target':'Settings'},'history':[]}
    m=tasks().helper('repair_stages');ctx=m.context(run,job)
    assert ctx['失败对象']['控件']=='Settings'
    assert ctx['任务目标']['控件']=='Policy'
    assert {c['名称'] for c in ctx['区块'][0]['控件']}=={'Policy','Settings'}
    req=tasks().helper('step_repair').request(ROOT,job,ctx)
    assert {c['name'] for c in req['original_request']['backend_candidates']}=={'Policy','Settings'}


def test_accepted_visual_location_does_not_expose_unaccepted_alternatives(tmp_path,monkeypatch):
    import importlib.util
    from PIL import Image
    m=tasks().helper('target_observation');frame=tmp_path/'f.png';Image.new('RGB',(100,100)).save(frame)
    original=importlib.util.module_from_spec
    def inject(spec):
        mod=original(spec)
        if spec.name=='target_match':
            loader=spec.loader.exec_module
            def execute(m):
                loader(m);m.locate=lambda *a:{'accepted':True,'box':[1,2,3,4],'candidates':[{'box':[5,6,7,8]}]}
            spec.loader.exec_module=execute
        return mod
    monkeypatch.setattr(importlib.util,'module_from_spec',inject)
    q={'action_ready':True,'source':{'region':'r'},'backend_candidates':[{'id':'c','name':'button','image':str(frame)}], 'image_refs':[str(frame)],'user_prompt':''}
    result=m.attach(q,{'r':{'controls':{'c':{}}}})
    assert result['target_observations'][0]['整屏候选位置']==[[1,2,3,4]]


def test_wait_allows_changing_frame_back_checks_surface(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as m
    monkeypatch.setattr(m.visual_backtrack,'same_surface',lambda *a:True)
    assert not m.system_action_changed('wait','before','after')
    assert not m.system_action_changed('back','before','after')
    monkeypatch.setattr(m.visual_backtrack,'same_surface',lambda *a:False)
    assert m.system_action_changed('back','before','after')
    assert not m.system_action_changed('wait','before','after')


def test_back_tolerates_small_clock_change_but_not_replaced_surface(tmp_path,monkeypatch):
    import numpy as np
    from PIL import Image
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as m
    pixels=np.random.default_rng(1).integers(0,256,(640,320,3),dtype=np.uint8)
    before=tmp_path/'before.png';after=tmp_path/'after.png'
    Image.fromarray(pixels).save(before)
    pixels[2:12,100:130]=255;Image.fromarray(pixels).save(after)
    assert not m.system_action_changed('back',before,after)
    Image.new('RGB',(320,640),'black').save(after)
    assert m.system_action_changed('back',before,after)


def test_back_uses_window_identity_despite_dynamic_pixels(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT));import run_task_step as m
    monkeypatch.setattr(m.visual_backtrack,'same_surface',lambda *args:False)
    assert not m.system_action_changed('back','before','after','clock-window','clock-window')
    assert m.system_action_changed('back','before','after','clock-window','dialog-window')
    assert m.system_action_changed('back','before','after','clock-window',None)
