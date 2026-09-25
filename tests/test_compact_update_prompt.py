import json
from copy import deepcopy
from tests.test_recovery_discovery import mod


def test_compact_wire_keeps_values_chains_unknowns_and_suffix():
    value={'任务目标':{'已有参数发现':{'状态':{'description':'最新 B','最新来源动作':'a0003'}},
        '相关历史动作与观察':[{'记录':ref,'观察':note,'参数观察':[{'属性':'状态','conditions':[],
            '原观察缺失字段':['evidence'],'来源对象':{'region':'旧区块','control':None}}]}
            for ref,note in [('a0001','A selected'),('a0002','other action'),('a0003','B selected')]]},
        '当前':{'text':'引号"、换行\n、反斜线\\都保留'}}
    suffix='\n\n截图坐标说明：原图像素。'
    q={'pipeline_step':'update','user_prompt':json.dumps(value,ensure_ascii=False,indent=2)+suffix,
       'screenshots':['before.png','after.png'],'response_schema':{'type':'object'}}
    before=deepcopy(q);result=mod('history_context').compact_update_prompt(q)
    decoded,end=json.JSONDecoder().raw_decode(result['user_prompt'])
    assert decoded==value and result['user_prompt'][end:]==suffix
    assert len(result['user_prompt'])<len(q['user_prompt'])
    assert q==before
    assert {k:v for k,v in result.items() if k!='user_prompt'}=={k:v for k,v in q.items() if k!='user_prompt'}
    assert mod('history_context').compact_update_prompt(result)==result


def test_other_stage_and_non_json_prompt_unchanged():
    for q in [{'pipeline_step':'action','user_prompt':'{}'},
              {'pipeline_step':'update','user_prompt':'本轮平台：桌面。\n{}'}]:
        assert mod('history_context').compact_update_prompt(q)==q
