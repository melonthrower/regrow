"""Prompt projections may share evidence only when identity and source agree."""
from copy import deepcopy
import json
from tests.test_recovery_discovery import mod
from tests.test_current_page_context import case


def test_incoming_history_references_only_matching_fields(tmp_path):
    records,state,_=case(tmp_path)
    a=records['world']['actions']['a1'];a['purpose']='Inspect the add entry once'
    a['result']['evidence']='Original after-frame evidence'
    records['dialog']['reached_by']=[{'source_region':'world','attempt':'a1'}]
    rows=mod('function_evidence').incoming_results(records['dialog'],records)
    conflict=deepcopy(rows[0]);conflict['区块变化']=[{'evidence':'different observation must survive'}]
    other=deepcopy(rows[0]);other['来源区块记录']='other-owner'
    raw=deepcopy([rows[0],conflict,other])
    q={'stage':'discovery','user_prompt':json.dumps({'历史进入记录（不证明当前可见或行为等价）':raw}),'screenshots':[]}
    mod('page_context').attach(q,records,state,usage='discovery')
    actual=json.loads(q['user_prompt'])['历史进入记录（不证明当前可见或行为等价）']
    assert '动作目的' not in actual[0] and '区块变化' not in actual[0]
    assert '结果' not in actual[0] and '依据' not in actual[0]
    assert 'Add city' in actual[0]['动作历史']
    assert actual[0]['动作前观察']=='base' and actual[0]['来源区块记录']=='world'
    assert actual[1]['区块变化']==conflict['区块变化']
    assert actual[2]==other
    text=q['user_prompt'];mod('page_context').refresh(q);assert q['user_prompt']==text
    assert rows[0]==raw[0]


def test_cards_keep_unique_details_without_restoring_old_state(tmp_path):
    records,state,frame=case(tmp_path)
    target=mod('target_observation');page=mod('page_context')
    card=target.describe(records['dialog']['controls']['submit'],'opened')
    card.update({'本次外观':'green border','功能疑问':'unknown save scope'})
    candidate={'id':'submit','name':'Add','region_ref':'dialog','region_name':'Add city dialog','target_observation':deepcopy(card)}
    q={'action_ready':True,'user_prompt':'choose the existing task','source':{'region':'dialog','observation':'opened'},'backend_candidates':[candidate],'screenshots':[str(frame)],'image_refs':[str(frame)]}
    q=target.refresh(q);page.attach(q,records,state)
    sent=q['target_observations'][0]['目标观察']
    assert '可见状态' not in sent
    assert 'disabled' not in q['_page_context_text'] and sent['功能疑问']=='unknown save scope'
    assert q['image_refs']==[str(frame)]
    assert candidate['target_observation']==card
    text=q['user_prompt'];q=target.refresh(q);assert q['user_prompt']==text
    q['page_context']['current_tree'][0]['controls'][1]['evidence']='needs_recheck'
    q=target.refresh(q)
    assert '可见状态' not in q['target_observations'][0]['目标观察']
    q['page_context']['current_tree'][0]['controls'][1].update(evidence='current_observation',state='enabled')
    q=target.refresh(q)
    assert '可见状态' not in q['target_observations'][0]['目标观察']
    q['page_context']['current_tree'][0]['controls'][1]['state']='disabled'
    q['backend_candidates'][0]['region_ref']='another-owner';q=target.refresh(q)
    assert '可见状态' not in q['target_observations'][0]['目标观察']


def test_planning_state_and_same_goal_have_one_body_without_losing_parent_goal(tmp_path):
    records,state,frame=case(tmp_path);page=mod('page_context');target=mod('target_observation')
    card=target.describe(records['dialog']['controls']['submit'],'opened')
    q={'stage':'task_proposal','user_prompt':json.dumps({'控件':[{'name':'Add','目标观察':card}]}),'source':{'region':'dialog','observation':'opened'},'screenshots':[str(frame)]}
    page.attach(q,records,state)
    assert '可见状态' not in json.loads(q['user_prompt'])['控件'][0]['目标观察']
    assert 'World / inspect' in q['_page_context_text']
    action={'action_ready':True,'user_prompt':'当前目标：inspect\nEnd after direct feedback','source':{'region':'dialog','task_region':'world','task_name':'inspect'},'screenshots':[str(frame)]}
    page.attach(action,records,state)
    assert '保留目标：World / inspect' not in action['_page_context_text']
    goal_line=next(line for line in action['_page_context_text'].splitlines() if line.startswith('保留目标：'))
    assert 'World' in goal_line and 'pending' in goal_line
    assert action['page_context']['goal']['name']=='inspect'
    assert '当前目标：inspect' in action['user_prompt']
    action['source']['task_name']='different task';page.refresh(action)
    assert '保留目标：World / inspect' in action['_page_context_text']
