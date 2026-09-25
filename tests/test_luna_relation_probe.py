from copy import deepcopy
import json
from types import SimpleNamespace
import pytest

from tools.luna_inventory_probe import merge_observation
from tools.luna_relation_probe import questions_for, apply_answers, answer_schema, run


def sample():
    return merge_observation({}, dict(reuse=[], regions=[dict(source_ref='', parent_ref='',
        label=str(i), function='Item', controls=[dict(label='Open', function='Open', kind='button', observation=''),
        dict(label='', function='Enable', kind='toggle', observation='')]) for i in range(2)], uncertain=[], complete=True))


def keep_answers(questions):
    return {key: dict(choice=('keep' if q['kind']=='partition' else 'keep_separate' if q['kind']=='repeated' else 'new'),
                      evidence='visible evidence', groups=[]) for key,q in questions.items() if q['kind']!='foreground'} | {
        'foreground': dict(excluded=[], uncertain=[], evidence='current foreground')}


def test_every_question_must_be_answered_without_mutating_candidate():
    view=sample();original=deepcopy(view);qs=questions_for({},view)
    answers=keep_answers(qs);answers.pop(next(k for k in qs if k!='foreground'))
    with pytest.raises(ValueError,match='every question'):
        apply_answers(view,qs,answers)
    assert view==original


def test_split_moves_existing_controls_and_cannot_invent_one():
    view=sample();qs=questions_for({},view);answers=keep_answers(qs)
    answers['partition_r1']=dict(choice='split',evidence='independent group',groups=[
        dict(label='Editor',function='Configure',controls=['r1:1'])])
    result=apply_answers(view,qs,answers)
    assert len(result['regions']['r1']['controls'])==1
    assert result['regions']['r3']['parent_ref']=='r1'
    assert result['regions']['r3']['controls'][0]['function']=='Enable'
    answers['partition_r1']['groups'][0]['controls']=['phantom']
    with pytest.raises(ValueError):apply_answers(view,qs,answers)


def test_same_list_preserves_each_physical_control_and_member_source():
    view=sample();qs=questions_for({},view);answers=keep_answers(qs)
    repeated=next(k for k,q in qs.items() if q['kind']=='repeated')
    answers[repeated]=dict(choice='same_list',evidence='same list repeated members',groups=[])
    result=apply_answers(view,qs,answers)
    assert len(result['regions'])==1
    region=next(iter(result['regions'].values()))
    assert len(region['controls'])==4
    assert len(region['members'])==2
    assert result['identity_verified'] is False


def test_foreground_exclusion_is_recorded_and_uncertainty_blocks_complete():
    view=sample();qs=questions_for({},view);answers=keep_answers(qs)
    answers['foreground']=dict(excluded=['r1:0'],uncertain=['r2:0'],evidence='background and ambiguous')
    result=apply_answers(view,qs,answers)
    assert len(result['regions']['r1']['controls'])==1
    assert not result['complete']
    assert result['excluded_controls']==['r1:0']


def test_schema_uses_actual_reference_choices_and_no_irrelevant_groups():
    qs=questions_for({},sample());schema=answer_schema(qs)
    refs=schema['properties']['foreground']['properties']['excluded']['items']['enum']
    assert refs==['r1:0','r1:1','r2:0','r2:1']
    repeated=next(k for k,q in qs.items() if q['kind']=='repeated')
    assert 'groups' not in schema['properties'][repeated]['properties']
    group=schema['properties']['partition_r1']['properties']['groups']['items']
    assert group['properties']['controls']['items']['enum']==['r1:0','r1:1']


def test_two_splits_cannot_claim_same_control():
    view=sample();qs=questions_for({},view);answers=keep_answers(qs)
    group=dict(label='Editor',function='Configure',controls=['r1:1'])
    answers['partition_r1']=dict(choice='split',evidence='evidence',groups=[group,group])
    with pytest.raises(ValueError):apply_answers(view,qs,answers)


@pytest.mark.parametrize('mode,count_expected',[('budget',1),('retry',1),('upgrade',0)])
def test_relation_transport_budget_and_model_lock(tmp_path,monkeypatch,mode,count_expected):
    from gui_rewalk.src.core.explore import agent as transport,api_config
    paid=[]
    def post(*args,**kwargs):
        paid.append(kwargs['json'])
        return SimpleNamespace(status_code=200,json=lambda:dict(model='gpt-5.6-luna',usage={}))
    class Agent:
        def __init__(self,**kwargs):pass
        def _call(self,**kwargs):
            model='gpt-5.6-sol' if mode=='upgrade' else 'gpt-5.6-luna'
            transport.requests.post('unused',json=dict(model=model))
            if mode=='retry':transport.requests.post('unused',json=dict(model=model))
            return dict(reuse=[],regions=[],uncertain=[],complete=False)
    monkeypatch.setattr(transport.requests,'post',post)
    monkeypatch.setattr(transport,'OpenAIAPIExplorerAgent',Agent)
    monkeypatch.setattr(api_config,'load_explore_api_config',lambda _:SimpleNamespace(base_url='',api_key='',timeout_seconds=1))
    frame=tmp_path/'frame.png';frame.write_bytes(b'saved frame')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps([dict(name='test',group='test',screenshot=str(frame))]))
    with pytest.raises(BaseException) as raised:run(manifest,tmp_path/'out',1)
    assert type(raised.value).__name__=='ProbeStop'
    assert len(paid)==count_expected
    assert transport.requests.post is post
