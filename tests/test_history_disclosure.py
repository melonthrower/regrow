import json
from copy import deepcopy
from tests.test_recovery_discovery import mod


def test_all_json_stages_preserve_complete_history_and_unknown_fields():
    for role in ('observation','task_proposal','observation_update','function_registration','recovery','branch_correction'):
        value={'历史':[{'attempt':str(i),'conditions':['old'],'evidence':None,'text':'多行\n"原文"'} for i in range(30)]}
        q={'role':role,'user_prompt':json.dumps(value,ensure_ascii=False,indent=2)+'\n截图说明','response_schema':{'type':'object'},'screenshots':['a.png']}
        original=deepcopy(q);result=mod('history_disclosure').project(q)
        decoded,end=json.JSONDecoder().raw_decode(result['user_prompt'])
        assert decoded==value and result['user_prompt'][end:]=='\n截图说明'
        assert q==original and result['screenshots']==q['screenshots'] and result['response_schema']==q['response_schema']


def test_repair_discloses_exact_target_and_keeps_original_rules_and_suffix():
    original={'本轮探索任务':'Exact task','任务目标':{'reason':'Observe only'},'历史':[{'status':'unknown'}]}
    d={'原任务要求':'Rules\nKeep conditions','原动态上下文':json.dumps(original,ensure_ascii=False)+'\n原图说明',
       '被拒绝回复':{'task_result':{'name':'Changed task'}},'具体校验错误':'missing actual task outcome',
       '相关记录与可用能力':{'other':'retain'}}
    q={'role':'step_correction','user_prompt':json.dumps(d,ensure_ascii=False,indent=2)+'\n新图说明'}
    result=mod('history_disclosure').project(q);p,end=json.JSONDecoder().raw_decode(result['user_prompt'])
    assert p['原动态上下文']['上下文']==original
    assert p['原动态上下文']['附加说明']=='\n原图说明'
    assert p['任务名称对照']=={'原任务':'Exact task','回复任务':'Changed task'}
    assert p['相关记录与可用能力']==d['相关记录与可用能力']
    assert 'Rules\nKeep conditions' in result['user_prompt'][end:]
    assert '\n新图说明' in result['user_prompt'][end:]
    assert mod('history_disclosure').project(result)==result


def test_action_groups_only_exact_source_headers_without_losing_facts():
    text='当前目标：Task\n- Region / Task / A：{"说明":"old"}\n- Region / Task / B：{"说明":"new"}\n其他历史保留'
    q={'role':'action_selection','user_prompt':text}
    result=mod('history_disclosure').project(q)['user_prompt']
    assert result.count('Region / Task')==1
    assert '- A：{"说明":"old"}' in result and '- B：{"说明":"new"}' in result
    assert result.endswith('其他历史保留')


def test_unparseable_context_and_unrecognized_role_remain_verbatim():
    for q in [{'role':'unknown','user_prompt':'{"x":1}'}, {'role':'recovery','user_prompt':'plain\nhistory'}]:
        assert mod('history_disclosure').project(q)==q


def test_malformed_rejected_task_result_can_still_reach_correction():
    for rejected in ('wrong type',['wrong type'],12):
        d={'原动态上下文':json.dumps({'本轮探索任务':'Task'}),'被拒绝回复':{'task_result':rejected}}
        result=mod('history_disclosure').project({'role':'step_correction','user_prompt':json.dumps(d)})
        value=json.loads(result['user_prompt'])
        assert value['被拒绝回复']['task_result']==rejected
        assert value['任务名称对照']=={'原任务':'Task','回复任务':None}
