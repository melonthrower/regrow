from tests.test_recovery_discovery import mod


def test_historical_navigation_has_no_current_directive():
 task={'status':'done','result_evidence':'当前可交互区块为菜单；后续优先探索菜单','completion_basis':{'destination_regions':['menu']}}
 assert mod('history_context').attempts(task,{'menu':{'name':'菜单'}})==['历史结果：该入口当时打开「菜单」。']


def test_findings_only_follow_task_or_same_control():
 m=mod('history_context');fact={'description':'Clock当前选中'}
 t={'control':'a','findings':{'time':{'description':'7:00'}}}
 rs={'r':{'name':'Alarm','tasks':{'current':t}},'nav':{'name':'导航','tasks':{'old':{'control':'clock','findings':{'selected':fact}}}}}
 lines,refs=m.findings(rs,{},'r','current',t)
 assert len(lines)==1 and 'Clock' not in lines[0]


def test_known_region_candidates_disclose_reason_not_visibility():
 m=mod('history_context');rs={'a':{'name':'Alarm','description':'old','controls':{}},'n':{'name':'导航','description':'nav','controls':{}}}
 rows=m.identity_candidates(rs,{'interactive_regions':['a']},{'region_ref':'a'},[{'name':'导航'}])
 assert all(x['当前状态']=='未由这份历史记录确认' for x in rows)
 assert '动作前来源' in rows[0]['提供原因']
 assert '截图外观匹配候选（不等于前景）' in rows[1]['提供原因']
