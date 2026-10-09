from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import control_identity_review as review

ROOT = Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def b(x, y, w=20, h=20):return dict(left=x, top=y, right=x+w, bottom=y+h)


def scene(tmp_path):
    pixels = np.random.default_rng(83).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    frame = tmp_path/'frame.png';Image.fromarray(pixels).save(frame)
    crop = tmp_path/'control.png';Image.fromarray(pixels[30:50, 40:60]).save(crop)
    o = dict(image=str(crop), source_image=str(frame), bbox=b(40, 30), image_quality='clear', image_quality_reason='synthetic fixture', evidence={'source_call':'old'})
    records = {'r1': {'name':'Timer', 'controls': {'c1': {'name':'Start', 'observations':[o]}}}}
    proposal = {'regions':[dict(name='Timer', previous_name='Timer', bbox=b(0, 0, 160, 120))],
        'controls':[dict(name='Triangle', region_index=0, previous_name='', bbox=b(40, 30))],
        'foreground':{'interactive_areas':[{'bbox':b(0,0,160,120)}]}}
    request = {'pipeline_step':'update', 'region_names':{'Timer':'r1'}, 'screenshots':[str(frame),str(frame)]}
    return records, frame, request, proposal


def pairs(tmp_path, data):
    records, frame, q, p = data
    return [pair for group in review.candidates(records, tmp_path, frame, q, p) for pair in group]


def test_unique_conflict_requires_scene_review_without_mutating_reply(tmp_path):
    data=scene(tmp_path);original=deepcopy(data[3]);found=pairs(tmp_path,data)
    assert len(found)==1 and found[0]['control']=='c1'
    assert found[0]['historical_frame']==str(data[1]) and found[0]['historical_box']==[40,30,60,50]
    with pytest.raises(review.Conflict):review.check(data[0],tmp_path,data[1],data[2],data[3])
    assert data[3]==original


def test_search_only_confirmed_owner_and_never_global(tmp_path):
    data=scene(tmp_path);records,_,_,p=data
    records['r2']=deepcopy(records['r1']);records['r2']['name']='Other'
    assert len(pairs(tmp_path,data))==1
    p['regions'][0]['previous_name']=''
    assert not pairs(tmp_path,data)


def test_multiple_old_candidates_not_hidden_by_vote_dedup(tmp_path):
    data=scene(tmp_path);data[0]['r1']['controls']['c2']=deepcopy(data[0]['r1']['controls']['c1'])
    assert len(pairs(tmp_path,data)) == 2
    with pytest.raises(review.CandidateConflict):review.check(data[0],tmp_path,data[1],data[2],data[3])


def test_same_screen_repeated_buttons_do_not_trigger_pair_calls(tmp_path):
    data=scene(tmp_path)
    with Image.open(data[1]) as im:pixels=np.array(im)
    pixels[70:90,100:120]=pixels[30:50,40:60];Image.fromarray(pixels).save(data[1])
    assert not pairs(tmp_path,data)


def test_second_strong_peak_excludes_even_with_score_gap():
    controls=[(0,{'bbox':b(0,0)})]
    hits={'c1':{'accepted':True,'candidates':[{'box':[0,0,20,20]},{'box':[80,80,100,100]}]}}
    assert not list(review.candidate_groups(controls,hits))
    hits['c1']['candidates']=hits['c1']['candidates'][:1]
    hits['c1']['candidates_truncated']=True
    assert not list(review.candidate_groups(controls,hits))


def test_two_current_reports_cannot_claim_single_old_candidate(tmp_path):
    data=scene(tmp_path);data[3]['controls'].append(deepcopy(data[3]['controls'][0]))
    assert not pairs(tmp_path,data)


def test_missing_original_scene_and_uncertain_owner_are_skipped(tmp_path):
    data=scene(tmp_path);data[0]['r1']['controls']['c1']['observations'][0]['source_image']='absent.png'
    assert not pairs(tmp_path,data)
    data=scene(tmp_path);data[3]['regions'][0]['identity']='uncertain'
    assert not pairs(tmp_path,data)


def correction(tmp_path):
    data=scene(tmp_path);pair=pairs(tmp_path,data)[0]
    q={'original_request':deepcopy(data[2]),'screenshots':list(data[2]['screenshots']),
       'response_schema':{'properties':{},'required':[]},'system_prompt':'full original system',
       'fixed_parts':[], 'user_prompt':json.dumps({'被拒绝回复':data[3], '原动态上下文':'full real context is retained'})}
    review.attach(ROOT,{'control_identity_pair':pair,'stage':'update'},q)
    return data,pair,q


def test_pair_request_keeps_native_context_and_does_not_duplicate_current_frame(tmp_path):
    data,pair,q=correction(tmp_path)
    assert q['screenshots']==data[2]['screenshots']
    assert json.loads(q['user_prompt'])['原动态上下文']=='full real context is retained'
    assert q['response_schema']['properties']['control_identity']['enum']==['same','different','uncertain']
    assert json.loads(q['user_prompt'])['本次只核对这一对控件']['当前对象']['图片']==2


@pytest.mark.parametrize('decision',['same','different'])
def test_explicit_reply_reuses_or_retains_distinct_identity(tmp_path,decision):
    data,pair,q=correction(tmp_path);p=deepcopy(data[3])
    q['user_prompt']+='\n实际发送时追加的截图说明和规则。'
    if decision=='same':p['controls'][0]['previous_name']='Start'
    r={'control_identity':decision,'resolution':'revise','proposal':p,'reason':'Compare scene context'}
    accepted=review.reviewed_request(q,r)
    review.check(data[0],tmp_path,data[1],accepted,p)
    assert p['controls'][0]['previous_name']==('Start' if decision=='same' else '')


def test_different_decision_survives_display_rename_and_list_reordering(tmp_path):
    data,_,q=correction(tmp_path);p=deepcopy(data[3])
    p['regions'][0]['name']='Timer panel'
    p['regions'].insert(0,dict(name='Other',previous_name='',bbox=None))
    p['controls'][0]['region_index']=1
    p['controls'][0]['name']='Distinct Triangle'
    accepted=review.reviewed_request(q,dict(control_identity='different',resolution='revise',proposal=p,reason='Different scene role'))
    review.check(data[0],tmp_path,data[1],accepted,p)


def test_uncertain_does_not_authorize_new_identity_or_replay(tmp_path):
    data,_,q=correction(tmp_path)
    with pytest.raises(ValueError,match='仍不确定'):
        review.reviewed_request(q,{'control_identity':'uncertain','resolution':'revise','proposal':data[3],'reason':'unknown'})
    original=review.reviewed_request(q,{'control_identity':'uncertain','resolution':'blocked','proposal':None,'reason':'unknown'})
    assert not original.get('control_identity_reviews')
    with pytest.raises(review.Conflict):review.check(data[0],tmp_path,data[1],original,data[3])


def test_distinct_decision_bound_to_same_object_and_frame(tmp_path):
    data,_,q=correction(tmp_path);r={'control_identity':'different','resolution':'revise','proposal':deepcopy(data[3]),'reason':'scene differs'}
    accepted=review.reviewed_request(q,r)
    r['proposal']['controls'][0]['bbox']=b(41,30)
    with pytest.raises(ValueError):review.reviewed_request(q,r)
    with Image.open(data[1]) as im:pixels=np.array(im)
    pixels[110,150]=[0,1,2];Image.fromarray(pixels).save(data[1])
    with pytest.raises(review.Conflict):review.check(data[0],tmp_path,data[1],accepted,data[3])


@pytest.mark.parametrize('reason',['Different context',' '])
def test_runner_accepts_unchanged_distinct_proposal_only_after_valid_review(tmp_path,reason):
    """Auxiliary Runner wiring check, not real-model/registration acceptance."""
    import step_repair
    from types import SimpleNamespace
    data=scene(tmp_path);records,frame,q,p=data
    q.update(system_prompt='fixture', user_prompt='{}', fixed_parts=[],
             response_schema={'type':'object','properties':{k:{} for k in p},'required':list(p)})
    replies=[deepcopy(p),dict(blocked_by='none',resolution='revise',reason=reason,
                            proposal=deepcopy(p),record_edit=None,control_identity='different')]
    calls=[]
    def call(request):
        ref=str(len(calls));calls.append(deepcopy(request));reply=replies[len(calls)-1]
        sent=deepcopy(request);sent['user_prompt']+='\nScreenshot roles appended by transport'
        step_repair.atomic(tmp_path/'calls'/ref/'request.json',sent)
        step_repair.atomic(tmp_path/'calls'/ref/'response.json',reply)
        return ref,reply
    runner=step_repair.Runner(ROOT,tmp_path,call,None,lambda:2-len(calls))
    def accept(root,run,job):
        review.check(records,tmp_path,frame,job['request'],job['candidate'])
        return {'registered':True}
    runner.adapters=SimpleNamespace(accept=accept,context=lambda *args:{})
    if not reason.strip():
        with pytest.raises(step_repair.Paused):runner.perform('update',q,'a1')
        pending=step_repair.pending(tmp_path)
        assert pending['control_identity_pair']
        assert not pending['request'].get('control_identity_reviews')
        assert not (tmp_path/'calls/1/effective_request.json').exists()
        return
    done=runner.perform('update',q,'a1')
    assert done['status']=='complete' and len(calls)==2
    assert done['request']['control_identity_reviews'][0]['decision']=='different'
    effective,candidate=step_repair.submission(tmp_path,'1')
    assert effective==done['request'] and candidate==p
    assert step_repair.read(tmp_path/'calls/0/response.json')==p


def test_multiple_candidates_select_once_then_compare_one_pair(tmp_path):
    """Auxiliary routing; model/native semantic acceptance is separate."""
    import step_repair
    from types import SimpleNamespace
    data=scene(tmp_path);records,frame,q,p=data
    records['r1']['controls']['c2']=deepcopy(records['r1']['controls']['c1'])
    records['r1']['controls']['c2']['name']='Resume'
    q.update(system_prompt='fixture', user_prompt='{}', fixed_parts=[],
             response_schema={'type':'object','properties':{k:{} for k in p},'required':list(p)})
    revised=deepcopy(p);revised['controls'][0]['previous_name']='Start'
    replies=[deepcopy(p),{'candidate':'Start','reason':'Current editor is visible'},
             dict(blocked_by='none',resolution='revise',reason='Same editor in both scenes',
                  proposal=revised,record_edit=None,control_identity='same')]
    calls=[]
    def call(request):
        ref=str(len(calls));calls.append(deepcopy(request));reply=replies[len(calls)-1]
        step_repair.atomic(tmp_path/'calls'/ref/'request.json',request)
        step_repair.atomic(tmp_path/'calls'/ref/'response.json',reply)
        return ref,reply
    runner=step_repair.Runner(ROOT,tmp_path,call,None,lambda:3-len(calls))
    published=[]
    def accept(root,run,job):
        review.check(records,tmp_path,frame,job['request'],job['candidate'])
        published.append(job['candidate'])
        return {'registered':True}
    runner.adapters=SimpleNamespace(accept=accept,context=lambda *args:{})
    done=runner.perform('update',q,'a1')
    assert done['status']=='complete' and len(calls)==3 and published==[revised]
    assert calls[1]['role']=='control_identity_selection'
    assert len(calls[1]['control_identity_candidates'])==2
    assert 'control_identity_pair' not in calls[1]
    assert calls[2]['control_identity_pair']['old_name']=='Start'
    assert calls[2]['control_identity_pair']['candidate_count']==2
    assert not (tmp_path/'calls/1/effective_request.json').exists()


def test_unselected_and_rejected_choice_cannot_create_identity(tmp_path):
    data,_,q=correction(tmp_path)
    pair=q['control_identity_pair'];pair['candidate_count']=2
    reply=dict(control_identity='different',resolution='revise',proposal=data[3],reason='Not selected object')
    with pytest.raises(ValueError,match='其他历史候选'):review.reviewed_request(q,reply)
    group=[pair,{**pair,'previous_name':'Resume','old_name':'Resume'}]
    q['user_prompt']='{}';q['original_request']=data[2]
    selection=review.selection_request(ROOT,{'control_identity_candidates':group},q)
    assert review.selected_pair(selection,{'candidate':None,'reason':'Insufficient context'}) is None
    with pytest.raises(Exception):review.selected_pair(selection,{'candidate':'Outside region','reason':'unknown'})


@pytest.mark.parametrize('decision',['same','different'])
def test_submission_rechecks_pair_without_effective_request(tmp_path,decision):
    import step_repair
    data,_,q=correction(tmp_path);q['role']='step_correction'
    proposal=deepcopy(data[3])
    if decision=='same':proposal['controls'][0]['previous_name']='Start'
    reply=dict(resolution='revise',proposal=proposal,record_edit=None,control_identity=decision,reason='scene evidence')
    step_repair.atomic(tmp_path/'calls/1/request.json',q)
    step_repair.atomic(tmp_path/'calls/1/response.json',reply)
    effective,candidate=step_repair.submission(tmp_path,'1')
    review.check(data[0],tmp_path,data[1],effective,candidate)
    if decision=='same':
        reply['proposal']['controls'][0]['previous_name']='Different historical button'
    else:reply['reason']=' '
    step_repair.atomic(tmp_path/'calls/1/response.json',reply)
    step_repair.atomic(tmp_path/'calls/1/effective_request.json',effective)
    with pytest.raises(ValueError):step_repair.submission(tmp_path,'1')


def test_selection_disclosure_keeps_original_rules_and_task_history(tmp_path):
    import history_disclosure,prompt_delivery
    _,pair,q=correction(tmp_path)
    q['original_request']['role']='observation_update'
    q['user_prompt']=json.dumps({'原任务要求':'original rules','原动态上下文':json.dumps({'任务历史':['a','b']})})
    selection=review.selection_request(ROOT,{'control_identity_candidates':[pair]},q)
    projected=history_disclosure.project(selection)
    data,end=json.JSONDecoder().raw_decode(projected['user_prompt'])
    assert data['原动态上下文']['上下文']['任务历史']==['a','b']
    assert 'original rules' in projected['user_prompt'][end:]
    assert prompt_delivery.effective_role(selection)=='observation_update'
