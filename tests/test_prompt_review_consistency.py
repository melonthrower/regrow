from tests.test_recovery_discovery import ROOT,mod
from tests.test_stepwise_deferral import setup


def test_update_assembled_prompt_and_time_values(tmp_path):
 import jsonschema
 m=mod('result_updater');q=m.build_update_request(ROOT,{'本轮探索任务':'时间'},[])
 assert '省略也按 false' not in q['system_prompt']
 assert '非枚举values填[]' not in q['system_prompt']
 assert '实际观察到的值' in q['system_prompt']
 schema=q['response_schema']['properties']['task_result']['properties']['findings']['items']
 jsonschema.validate({'name':'时间','description':'编辑器显示','domain':{'type':'time','values':['08:15 PM'],'min':None,'max':None},'conditions':[],'evidence':'截图'},schema)


def test_task_inventory_uses_same_value_rules(tmp_path):
 import task_proposer
 run,q,d=setup(tmp_path);_,records,state=d.load(run)
 q=task_proposer.plan_request(ROOT,records,state,'r1')
 assert '共享/参数观察值.prompt' in [p['path'] for p in q['fixed_parts']]


def test_group_diagnostic_reuses_group_manual():
 m=mod('registration_diagnostics')
 report=m.collect('discovery',{}, {'regions':[{'name':'Menu','identity':'new','previous_name':None,'parent_index':None}], 'controls':[{'region_index':0,'name':n,'identity':'new','previous_name':None,'list_group':'period'} for n in ['AM','PM']]},{})
 row=next(e for e in report['errors'] if e['code']=='list_representative')
 assert 'bbox覆盖同组' in row['repair']
 assert '其余写excluded' not in row['repair']


def test_update_goal_keeps_previous_judgment_without_inventing_one():
 m=mod('history_context')
 task={'task_type':'parameter','reason':'观察修改反馈','result_evidence':'尚未确认，未见保存后的卡片变化','findings':{}}
 goal=m.task_goal(task,{})
 assert goal['原任务已有判断']['当时判断']==task['result_evidence']
 assert goal['reason']==task['reason']
 assert '原任务已有判断' not in m.task_goal({'reason':'观察输入反馈'},{})


def test_completion_and_empty_field_instructions():
 pr=ROOT/'遍历prompt'
 assert '非equivalent时，equivalent_to填空字符串' in (pr/'任务/区块探索任务.prompt').read_text()
 assert '保存后反馈' in (pr/'任务/任务结果核对.prompt').read_text()
 assert '本轮schema' in (pr/'发现手册/输出填写.prompt').read_text()
 assert '旧诊断不是本轮规则' in (pr/'纠错/步骤纠正.prompt').read_text()


def test_task_end_rule_is_shared_by_proposal_action_and_update(tmp_path):
 import task_proposer
 import json
 pr=ROOT/'遍历prompt';part='共享/任务结束条件.prompt'
 run,_,d=setup(tmp_path);_,records,state=d.load(run)
 proposal=task_proposer.plan_request(ROOT,records,state,'r1')
 update=mod('result_updater').build_update_request(ROOT,{'本轮探索任务':'查看选项'},[])
 for q in (proposal,update):assert part in [p['path'] for p in q['fixed_parts']]
 assert part in json.loads((pr/'流程/02_动作选择.json').read_text())['parts']


def test_observed_options_can_complete_parameter_survey_without_selection():
 m=mod('region_tasks');task={'task_type':'parameter','control':'c1','attempts':[],'findings':{}}
 owner={'id':'r1','tasks':{'查看选项':task}}
 reply={'action_result':{'exception':'none'},'task_result':{'name':'查看选项','status':'done','evidence':'仅打开选项，看到Digital与Analog；未选择',
 'findings':[{'name':'样式','description':'可见选项','domain':{'type':'enum','values':['Digital','Analog'],'min':None,'max':None},'conditions':[],'evidence':'打开后的截图'}]}}
 m.settle_task(owner,{'task_name':'查看选项','control_ref':'c1','region_ref':'r1'},reply,'a1')
 assert task['status']=='done' and task['attempts']==['a1']
 assert '未选择' in task['result_evidence']
