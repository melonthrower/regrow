"""Current screenshot determines values; history records exploration efforts."""
from copy import deepcopy
import json
import page_context
import target_observation
import control_history_context
from tests.test_current_page_context import case
from tests.test_stepwise_region_tasks import ROOT


def test_target_card_does_not_republish_observed_display_as_current():
    c={'name':'Duration value','observations':[{'text':'old-display-471',
       'state':'old-state-472','icon_description':'digit field',
       'possible_operation':'edit duration','evidence':{'observation':'observed'}}]}
    before=deepcopy(c)
    for obs in ['observed','new-frame']:
        card=target_observation.describe(c,obs)
        assert 'old-display-471' not in json.dumps(card)
        assert 'old-state-472' not in json.dumps(card)
        assert card['功能推测（未验证）']=='edit duration'
    assert c==before


def test_history_identity_card_keeps_role_without_old_display():
    r={'controls':{'c':{'name':'Duration value','observations':[
        {'text':'old-display-473','state':'old-state-474','icon_description':'digit field',
         'possible_operation':'edit duration','evidence':{'observation':'observed'}}]}},'tasks':{}}
    before=deepcopy(r);card=control_history_context.describe(r,'c')
    assert 'old-display-473' not in json.dumps(card)
    assert 'Duration value' in json.dumps(card) and 'edit duration' in json.dumps(card)
    assert r==before


def test_map_uses_current_frame_and_keeps_efforts_without_old_control_state(tmp_path):
    records,state,frame=case(tmp_path)
    records['dialog']['controls']['submit']['observations'][0]['state']='old-state-475'
    before=deepcopy((records,state))
    q={'stage':'task_proposal','user_prompt':'{}','screenshots':[str(frame)]}
    page_context.attach(q,records,state,run=tmp_path)
    assert 'old-state-475' not in q['user_prompt']
    assert 'Observed actual result' in q['user_prompt'] and '已登记' in q['user_prompt']
    assert q['screenshots']==[str(frame)] and (records,state)==before


def test_frame_refresh_drops_old_target_fields_even_from_existing_card(tmp_path):
    records,state,frame=case(tmp_path)
    q={'stage':'action_selection','action_ready':True,'user_prompt':'goal',
       'screenshots':[str(frame)],'image_refs':[str(frame)],
       'source':{'region':'dialog','observation':'opened'},
       'backend_candidates':[{'id':'submit','name':'Add','target_observation':{
           '文字':'old-display-476','可见状态':'old-state-477','功能疑问':'not tested'}}]}
    page_context.attach(q,records,state,run=tmp_path)
    target_observation.render(q)
    assert 'old-display-476' not in q['user_prompt'] and 'old-state-477' not in q['user_prompt']
    assert 'not tested' in q['user_prompt'] and 'Observed actual result' in q['user_prompt']
