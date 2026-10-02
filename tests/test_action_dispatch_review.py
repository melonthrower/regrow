import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'
spec=importlib.util.spec_from_file_location('dispatch_repair',ROOT/'step_repair.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def episode(run):
    q={'screenshots':['fresh.png']}
    proposal={'action':'click','target':'Pause','x':20,'y':30}
    job={'stage':'action','status':'complete','repairs':1,'call':'0020','candidate':proposal,
         'pre_dispatch_review':{'before':'old.png','current':'fresh.png','window':'window1'},
         'request':q}
    m.atomic(run/'calls/0020/request.json',{'role':'step_correction','original_request':q,'screenshots':['fresh.png']})
    m.atomic(run/'calls/0020/response.json',{'resolution':'revise','blocked_by':'none','proposal':proposal})
    return job

def test_only_this_round_specific_review_can_confirm(tmp_path):
    job=episode(tmp_path)
    assert m.confirmed_dispatch_review(tmp_path,job,['0020'],'window1','fresh.png')
    assert not m.confirmed_dispatch_review(tmp_path,job,[],'window1','fresh.png')
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],'new-dialog','fresh.png')
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],None,'fresh.png')
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],'window1','new-round.png')
    job.pop('pre_dispatch_review')
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],'window1','fresh.png')

def test_correction_uses_only_latest_frame_as_execution_basis(tmp_path):
    job=episode(tmp_path)
    job.update(history=[],supplements=[],error='frame changed')
    job['request'].update(system_prompt='Select an action',user_prompt='Inspect current target',response_schema={'type':'object'})
    request=m.request(ROOT,job,{})
    assert request['screenshots']==['fresh.png']
    assert request['original_request']['screenshots']==['fresh.png']
    assert '唯一' in request['user_prompt'] and '最新投递前画面' in request['user_prompt']
    assert any(p['path']=='纠错/投递前画面变化.prompt' for p in request['fixed_parts'])

@pytest.mark.parametrize('change',['second_repair','different_frame','different_proposal','other_error','already_dispatched'])
def test_other_revisions_do_not_authorize_dispatch(tmp_path,change):
    job=episode(tmp_path)
    if change=='second_repair':job['repairs']=2
    if change=='different_frame':job['request']['screenshots']=['unreviewed.png']
    if change=='different_proposal':job['candidate']={**job['candidate'],'x':99}
    if change=='other_error':
        m.atomic(tmp_path/'calls/0020/response.json',{'resolution':'revise','blocked_by':'binding_conflict','proposal':job['candidate']})
    if change=='already_dispatched':m.atomic(tmp_path/'execution_pending.json',{'attempt':'a1'})
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],'window1','fresh.png')


def test_confirmation_rejects_request_with_extra_historical_image(tmp_path):
    job=episode(tmp_path)
    path=tmp_path/'calls/0020/request.json'
    q=m.read(path);q['screenshots'].insert(0,'old.png');m.atomic(path,q)
    assert not m.confirmed_dispatch_review(tmp_path,job,['0020'],'window1','fresh.png')
