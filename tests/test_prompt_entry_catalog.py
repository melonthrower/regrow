"""Editing the common entry must affect real composition, not just its index."""
from copy import deepcopy
import json
from pathlib import Path
from regrow.runtime import action_commands as action_commands
from regrow.prompts import history_disclosure as history_disclosure
from regrow.prompts import output as output_contract
from regrow.prompts import output as prompt_delivery
from regrow.prompts import compose as prompt_rules
from regrow.prompts import compose as step_questions
from regrow.paths import SOURCE_ROOT
ROOT = SOURCE_ROOT

def editable_catalog(tmp_path, monkeypatch):
    path = tmp_path / '调用组成.json'
    path.write_text(json.dumps(prompt_rules.catalog(), ensure_ascii=False))

    def read(root=None):
        return json.loads(path.read_text())
    monkeypatch.setattr(prompt_rules, 'catalog', read)
    monkeypatch.setattr(step_questions, 'catalog', read)
    monkeypatch.setattr(prompt_delivery, 'catalog', read)
    return path

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))

def test_question_material_and_output_edits_reach_the_same_section(tmp_path, monkeypatch):
    path = editable_catalog(tmp_path, monkeypatch)
    value = {'目标应用': 'App', '新增证据槽': '事实只出现一次', '其他事实': '保留'}
    request = {'role': 'observation', 'discovery_context': {'mode': 'local'}}
    data = json.loads(path.read_text())
    section = data['calls']['observation']['groups'][0]
    section.update(question='这次只核对什么？', materials=['新增证据槽'], output='提交本次确认')
    write(path, data)
    rendered = step_questions.render(value, request, history_disclosure.readable)
    first = rendered.split('## 问题 2：')[0]
    assert '这次只核对什么？' in first and '提交本次确认' in first
    assert rendered.count('事实只出现一次') == 1 and '事实只出现一次' in first
    assert '其他事实' in rendered and '目标应用' in rendered

def test_action_layout_and_slots_are_loaded_on_each_request(tmp_path, monkeypatch):
    path = editable_catalog(tmp_path, monkeypatch)
    value = {'当前任务': {'task': 'r1/了解预览'}, '登记页面组成与访问来路': '已选择文件', '自定义控件槽': 'r1/c2 预览', '限制': '保留真实失败'}
    data = json.loads(path.read_text())
    action = data['calls']['action_selection']
    action['materials']['controls'] = '自定义控件槽'
    action['sections'][2]['title'] = '本轮对象'
    data['calls']['action_selection']['question'] = '为了原问题下一步选什么？'
    write(path, data)
    result = step_questions.render(value, {'role': 'action_selection'}, history_disclosure.readable)
    assert '## 本轮对象\nr1/c2 预览' in result and result.count('r1/c2 预览') == 1
    assert result.index('已选择文件') < result.index('为了原问题下一步选什么？')
    assert '保留真实失败' in result
    data['calls']['action_selection']['question'] = '同进程再次编辑的问题'
    write(path, data)
    assert '同进程再次编辑的问题' in step_questions.render(value, {'role': 'action_selection'}, history_disclosure.readable)

def test_fixed_parts_platform_and_output_prose_share_the_editable_entry(tmp_path, monkeypatch):
    path = editable_catalog(tmp_path, monkeypatch)
    data = json.loads(path.read_text())
    data['calls']['task_proposal']['parts'] = ['任务/区块功能登记.prompt']
    data['platforms']['desktop']['action_roles'].append('task_proposal')
    data['output']['action_text']['intro'] = '测试用的字段要求'
    write(path, data)
    assert [p['path'] for p in prompt_rules.parts(ROOT, 'task_proposal')] == ['任务/区块功能登记.prompt']
    assert '### 动作与参数' in next(prompt_delivery.desktop_parts(ROOT, {'role': 'task_proposal'}))['text']
    schema = action_commands.selection_schema(action_commands.schema())
    original = deepcopy(schema)
    request = {'role': 'action_selection', 'system_prompt': '', 'fixed_parts': [], 'response_schema': schema}
    prepared = output_contract.prepare(request, ROOT)
    assert '测试用的字段要求' in prepared['system_prompt']
    assert schema == original and prepared['response_schema'] == original
    assert output_contract.prepare(prepared, ROOT) == prepared

def test_normal_role_and_supplement_files_resolve_from_catalog():
    definition = prompt_rules.catalog(ROOT)
    for role in ('observation', 'task_proposal', 'action_selection', 'observation_update', 'function_registration', 'recovery'):
        paths = [p['path'] for p in prompt_rules.parts(ROOT, role)]
        assert paths and all(((ROOT / 'regrow/prompts' / p).is_file() for p in paths))
    local = prompt_rules.parts(ROOT, 'observation', selection={'mode': 'local'})
    global_view = prompt_rules.parts(ROOT, 'observation', selection={'mode': 'global'})
    assert local[0]['path'] == '任务/工作区块定位.prompt'
    assert global_view[0]['path'] == '任务/当前区块重定位.prompt'
    for (name, path) in definition['supplements'].items():
        assert prompt_rules.supplement(ROOT, name)['path'] == path

def test_task_review_default_group_and_shared_question_are_not_overridden(tmp_path, monkeypatch):
    path = editable_catalog(tmp_path, monkeypatch)
    data = json.loads(path.read_text())
    data['calls']['task_result_review']['question'] = '本轮复核问题'
    data['calls']['task_result_review']['groups'][0]['question'] = '只按这组证据判断'
    data['calls']['task_result_review']['groups'][0]['output'] = '本轮复核输出'
    write(path, data)
    text = step_questions.render({'原任务引用': 'r1/问题'}, {'role': 'task_result_review'}, history_disclosure.readable)
    assert '本轮复核问题' in text and '只按这组证据判断' in text and ('本轮复核输出' in text)
    data['calls']['action_selection']['question'] = '唯一动作问题'
    assert step_questions.work_question(data, 'action') == '唯一动作问题'
    assert step_questions.work_question(data, 'navigate') == '唯一动作问题'

def test_changed_glossary_path_keeps_its_group_and_saved_version(tmp_path, monkeypatch):
    import shutil
    root = tmp_path / 'source'
    shutil.copytree(ROOT / 'regrow/prompts', root / 'regrow/prompts')
    path = root / 'regrow/prompts/流程/调用组成.json'
    data = json.loads(path.read_text())
    data['output']['glossary_path'] = '共享/改名术语.prompt'
    shutil.copy2(root / 'regrow/prompts/共享/术语定义.prompt', root / 'regrow/prompts/共享/改名术语.prompt')
    write(path, data)
    q = {'role': 'action_selection', 'response_schema': action_commands.selection_schema(action_commands.schema()), 'fixed_parts': [], 'system_prompt': ''}
    sent = output_contract.prepare(q, root)
    assert sent['system_prompt'].startswith('# 术语定义\n\n### 通用')
    index = next((i for (i, p) in enumerate(sent['fixed_parts']) if p['path'] == '共享/改名术语.prompt/片段-通用'))
    old = sent['fixed_parts'][index]['text']
    new = old + '\nRetained glossary instruction.'
    sent['fixed_parts'][index]['text'] = new
    sent['system_prompt'] = sent['system_prompt'].replace(old, new, 1)
    again = output_contract.prepare(sent, root)
    assert again == sent and again['system_prompt'].count('Retained glossary instruction.') == 1
