"""Action materials share one identity catalogue without broad history recall."""
from copy import deepcopy
from pathlib import Path
import sys
import json
ROOT = Path(__file__).parents[1] / 'src'
sys.path.insert(0, str(ROOT))
from regrow.records.object_store import Records as Records
from regrow.records.object_store import owned_controls as owned_controls
from regrow.records.object_store import owned_tasks as owned_tasks
from regrow.records.object_store import owned_actions as owned_actions
from regrow.records.region_evidence import new_region as new_region
from regrow.records import action_candidates as action_candidates
from regrow.traversal import action_binding as action_binding
from regrow.prompts import target_observation as target_observation
from regrow.prompts import compose as step_questions
from regrow.prompts import history_disclosure as history_disclosure
from regrow.records import history_context as history_context

def fixture():
    rs = Records({rid: new_region(rid, name) for (rid, name) in [('r0001', '内容区'), ('r0002', '工具栏'), ('r0003', '当前弹层')]})
    for (rid, cid, name, obs) in [('r0001', 'c0001', '旧入口', 'old'), ('r0002', 'c0002', '解锁', 'now'), ('r0003', 'c0003', '编辑', 'now')]:
        owned_controls(rs[rid])[cid] = {'name': name, 'knowledge': '已知用途。', 'observations': [{'image': 'identity.png', 'evidence': {'observation': obs}}]}
    owned_tasks(rs['r0003'])['编辑反馈'] = {'name': '编辑反馈', 'control': 'c0003', 'status': 'pending', 'task_type': 'control_effect'}
    owned_actions(rs['r0001'])['a1'] = {'control': 'c0001', 'delivery': 'executed_receipt_zero'}
    rs['r0001']['transitions'] = [{'source_control': 'c0001', 'attempt': 'a1', 'target_region': 'r0003'}]
    state = {'working_region': 'r0003', 'interactive_regions': ['r0003', 'r0002'], 'active_task': {'region': 'r0003', 'name': '编辑反馈'}, 'observation': {'id': 'now', 'control_refs': ['c0003', 'c0002']}}
    q = {'action_ready': True, 'stage': 'action_selection', 'user_prompt': '{}', 'backend_candidates': [], 'source': {'region': 'r0003', 'observation': 'now', 'task_region': 'r0003', 'task_name': '编辑反馈', 'task_control': 'c0003'}}
    return (rs, state, q)

def test_current_foreground_controls_share_catalogue_and_old_arrival_is_omitted():
    (rs, state, q) = fixture()
    before = deepcopy(rs.packed())
    action_candidates.attach_related(q, rs, state)
    assert {(c['region_ref'], c['id']) for c in q['backend_candidates']} == {('r0003', 'c0003'), ('r0002', 'c0002')}
    assert '当前前景的相关外层身份候选' not in q['user_prompt']
    assert rs.packed() == before

def test_explicit_navigation_can_still_recall_old_trigger_without_promoting_owner():
    (rs, state, q) = fixture()
    q['navigation_path'] = [{'source_region': 'r0001', 'source_control': 'c0001'}]
    action_candidates.attach_related(q, rs, state)
    old = next((c for c in q['backend_candidates'] if c['id'] == 'c0001'))
    assert old['region_ref'] == 'r0001' and old['candidate_scope'] == 'foreground_entry_trigger'
    assert 'r0001' not in state['interactive_regions']

def test_single_catalogue_has_binding_refs_and_preserves_real_doubt_not_empty_source_fields():
    (rs, state, q) = fixture()
    action_candidates.attach_related(q, rs, state)
    for c in q['backend_candidates']:
        c['region_name'] = rs[c['region_ref']]['name']
        c['knowledge'] = '已知用途。'
        c['target_observation'] = {'观察来源': 'secret-internal-call', '登记外观': '', '功能疑问': '标签被遮挡'}
    q['user_prompt'] = json.dumps({'目标控件记录': ['old'], '可登记动作身份': ['old'], '当前前景的相关外层身份候选': ['old']})
    action_binding.disclose_candidates(q)
    body = json.loads(q['user_prompt'])
    assert set(body) == {'相关控件'}
    assert '观察来源' not in body['相关控件'] and '登记外观' not in body['相关控件']
    assert '标签被遮挡' in body['相关控件']
    for row in action_binding.candidate_rows(q):
        assert body['相关控件'].count(row['target']) == 1
        assert action_binding.candidate_matches(q, row['target']) == [row['candidate']]

def test_action_has_one_question_and_retains_full_task_description_and_failures():
    (rs, state, q) = fixture()
    task = rs.tasks['r0003/编辑反馈']
    task['reason'] = '了解编辑如何生效，以及确认后的界面变化。'
    task['blocker'] = {'reason': '内容仍被锁定'}
    (material, _) = history_context.action_context(rs, state, 'r0003', '编辑反馈', task)
    material.update({'本轮工作': {'范围': '当前弹层'}, '相关控件': 'r0003/c0003 编辑', '登记页面组成与访问来路': 'a1：输入；文字未发送。', '未解除的应用退出记录': '旧失败仍有效'})
    text = step_questions.render(material, {'role': 'action_selection'}, history_disclosure.readable)
    assert text.count('## 下一步') == 1 and '## 问题 2' not in text
    assert '了解编辑如何生效，以及确认后的界面变化。' in text
    assert '内容仍被锁定' in text and '文字未发送' in text and ('旧失败仍有效' in text)
    assert '见输出要求' not in text and task.ref in text

def test_region_constraints_and_empty_display_region_survive_control_list_merge():
    (rs, state, q) = fixture()
    action_candidates.attach_related(q, rs, state)
    q['page_context'] = {'current_tree': [{'ref': 'r0003', 'name': '当前弹层', 'children': [], 'knowledge': {'local_knowledge': {'k0001': '先解锁，再编辑。'}, 'constraints': {'编辑限制': '只读模式不能提交'}}, 'controls': []}, {'ref': 'r0004', 'name': '状态展示区', 'children': [], 'knowledge': {'local_knowledge': {'k0002': '显示当前进度。'}}, 'controls': []}]}
    target_observation.render(q)
    body = json.loads(q['user_prompt'])['相关控件']
    assert '先解锁，再编辑。' in body and '只读模式不能提交' in body
    assert 'r0004 状态展示区' in body and '显示当前进度。' in body

def test_navigation_without_action_task_card_keeps_original_question():
    value = {'本轮工作': {'范围': '目标页面', '目的': '先到达编辑区继续原问题', '关联任务': {'区块': '编辑区', '任务': '了解保存方式'}, '原问题': '了解文件保存的方式、条件及反馈。'}, '导航目标': '编辑区', '相关控件': 'r0001/c0001 编辑入口'}
    text = step_questions.render(value, {'role': 'action_selection'}, history_disclosure.readable)
    assert '了解文件保存的方式、条件及反馈。' in text and '先到达编辑区继续原问题' in text
    assert '了解保存方式' in text and text.count('## 下一步') == 1
