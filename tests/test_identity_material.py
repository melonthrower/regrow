"""Offline presentation/contract checks, not native Luna or GUI acceptance.

The example transcribes facts from the supplied user.prompt. c9001 and the
two frame paths are synthetic bindings; the original stable control ID and
screenshots were not supplied. No image is fabricated or sent to a model.
"""
from copy import deepcopy
import json
import pytest

from regrow.paths import SOURCE_ROOT
from regrow.prompts import history_disclosure, object_blocks, output, prompt_material
from regrow.recognition import control_identity_review as review, control_indexes
from regrow.records import page_context


def example_case():
    descriptions = [
        ('快捷键搜索输入', '输入搜索词可筛选快捷键列表；本次输入“search”后，结果区显示“Search”和“Cancel search”两项。该观察尚不能确定具体匹配字段、搜索规则或输入限制。'),
        ('大小写处理', '本次将查询从“search”替换为“SEARCH”后，结果仍为“Search”和“Cancel search”；该比较支持此查询的匹配不区分大小写。'),
        ('搜索词与可见条目文本的匹配', '输入“Cancel”后结果仅显示“Cancel search”；该观察支持搜索词与此可见条目文本匹配，但尚不能确定其他匹配字段或完整搜索规则。'),
        ('快捷键标记匹配', '输入“Escape”后，结果包含快捷键标记为“Escape”的“Cancel search”。这支持该查询匹配此结果显示的快捷键标记；尚不能据此确认多键组合的匹配规则。'),
        ('多键快捷键中的修饰键匹配', '输入“Ctrl”后，结果显示快捷键为 Ctrl+Q 的 Quit 和 Ctrl+S 的 Search；支持搜索词可匹配这些结果显示的多键快捷键中的 Ctrl。'),
    ]
    observations = [
        '点击搜索框、全选并输入“search”后，搜索框显示该文本，快捷键对话框切换为搜索结果视图，列表缩减为“Search”和“Cancel search”两项。',
        '点击搜索框、全选并输入全大写“SEARCH”后，搜索框显示新文本，搜索结果仍为“Search”和“Cancel search”两项。',
        '输入“Cancel”后结果仅显示“Cancel search”。',
        '输入“Escape”后，结果包含快捷键标记为“Escape”的“Cancel search”。',
        '搜索框中的“Escape”被替换为“Ctrl”，结果列表更新为两项：Ctrl+Q 对应 Quit，Ctrl+S 对应 Search。',
    ]
    facts, events = {}, {}
    for number, ((name, description), text, observation) in enumerate(zip(
            descriptions, ['search', 'SEARCH', 'Cancel', 'Escape', 'Ctrl'], observations), 5):
        aid = f'a{number:04d}'
        source = {'region': 'r0009', 'control': 'c9001', 'attempt': aid,
                  'source_call': f'{number:04d}', 'observation': 'example-old-observation', 'basis': 'explored'}
        facts[name] = {'name': name, 'description': description, 'source': source,
                       'sources': [source], 'observations': [{'description': description, 'source': source}]}
        events[aid] = {'region': 'r0009', 'control': 'c9001', '区块': '快捷键搜索输入区',
                      '入口': '快捷键搜索输入框', '身份关联': '已登记', '动作': 'input_text',
                      '执行': 'executed_receipt_zero', 'task': 'r0009/参数探索', '观察': observation,
                      '实际执行': [{'action': 'click'}, {'action': 'select_all'}, {'action': 'input_text', 'text': text}],
                      '来源': {'result_call': 'example-call', 'after_image': 'internal/after.png'}}
        if number > 5:
            events[aid]['动作前区块'] = ['Shortcuts 对话框标题栏', '快捷键列表区', '快捷键搜索输入区']
            events[aid]['动作后可交互区块'] = ['快捷键列表区', '快捷键搜索输入区', 'Shortcuts 对话框标题栏']
    context = {'name': '快捷键搜索输入框', 'description': '带放大镜图标的单行文本输入框，用于输入快捷键搜索内容。',
               'knowledge': '推测用途：输入搜索词可筛选快捷键列表；需要探索',
               'constraints': {name: {'name': name, 'description': description} for name, description in descriptions},
               '关联任务': [{'name': '参数探索', 'status': 'pending', 'findings': facts,
                         'result_evidence': '搜索“Ctrl”后显示 Ctrl+Q（Quit）和 Ctrl+S（Search）；完整组合的匹配规则、输入格式或取值、长度限制仍未回答。'}],
               '实际尝试与来源': events}
    task = {'task': 'r0009/参数探索', 'control_name': '快捷键搜索输入框', 'task_type': 'parameter',
            'status': 'pending', 'reason': '调查可输入、选择或调整内容的使用方式、取值规则及限制。',
            '未答部分': '输入完整快捷键组合（如“Ctrl+Q”）时如何匹配？输入格式以及取值或长度限制是什么？',
            '已确认规则': [description for _, description in descriptions],
            '当前控件知识': [{'index': 0, 'description': context['knowledge'], 'conditions': [], 'constraints': context['constraints']}]}
    body = {'当前任务': task, '实际来源区块': '快捷键搜索输入区', '实际入口': '快捷键搜索输入框',
            '实际动作': [{'action': 'click', 'x': 664, 'y': 321}, {'action': 'select_all', 'method': 'CTRL+A'},
                        {'action': 'input_text', 'text': 'Ctrl+Q'}],
            '回执': {'exit_code': 0, 'semantic_result': 'unverified', 'text_delivered': True, 'input_mode': 'replace'}}
    original = {'role': 'observation_update', 'stage': 'update', 'source': {'attempt': 'a0010'},
                'work_context': {'kind': 'update', 'region': 'r0009', 'attempt': 'a0010'},
                'user_prompt': json.dumps(body, ensure_ascii=False),
                'response_schema': {'type': 'object', 'properties': {}}, 'screenshots': ['current.png'],
                'control_indexes': ['c9001', 'c9002'],
                'page_context': {'history': {'events': deepcopy(events), 'names': {'r0009': '快捷键搜索输入区'}}}}
    pair = {'kind': 'reuse', 'key': 'synthetic-pair', 'region': 'r0009', 'control': 'c9001',
            'region_index': 0, 'control_index': 0, 'region_ref': 'r0009', 'ref': 'c9001', 'submitted_ref': 'c9001',
            'region_name': '快捷键搜索输入区', 'old_name': '快捷键搜索输入框', 'current_name': '快捷键搜索输入框',
            'current_box': None, 'historical_box': [506, 304, 844, 338],
            'historical_frame': 'historical.png', 'current_frame': 'current.png',
            'historical_evidence': {'source_call': '0024', 'source_field': '/controls/1', 'observation': 'update:0024'},
            'historical_description': '', 'region_description': '包含快捷键搜索输入框的区域；当前输入框显示“Ctrl”。',
            'current_candidates': [], 'context': context}
    candidate = {'regions': [{'name': '快捷键搜索输入区', 'ref': 'r0009'}],
                 'controls': [{'index': 0, 'region_index': 0}]}
    job = {'stage': 'update', 'attempt': 'a0010', 'control_identity_pair': pair,
           'candidate': candidate, 'history': [{'call': 'old-call', 'error': 'internal bookkeeping'}],
           'supplements': [], 'error': '核对身份', 'repairs': 2, 'request': original}
    request = {'original_request': deepcopy(original), 'page_context': deepcopy(original['page_context'])}
    return job, request


def build():
    job, request = example_case()
    return review.attach(SOURCE_ROOT, job, request)


def render(request):
    request = control_indexes.prepare(request)
    request = output.prepare(request, SOURCE_ROOT)
    return control_indexes.display(history_disclosure.project(request))


def ids(request):
    return {p['path'].partition('/片段-')[2] for p in object_blocks.select(SOURCE_ROOT, request)}


def test_comparison_keeps_identity_examples_without_registration_teaching():
    sent = render(build())
    assert {'control.definition', 'control.identity'} <= set(sent['object_blocks'])
    assert not {'control.references', 'shared.registration'} & set(sent['object_blocks'])
    assert 'region_index' not in sent['system_prompt'] and '`index`' not in sent['system_prompt']
    assert '小时增加按钮和分钟增加按钮' in sent['system_prompt']
    assert '同一搜索框输入不同文字' in sent['system_prompt']


def test_registration_still_gets_references_and_examples_once():
    request = {'role': 'observation', 'response_schema': {'type': 'object', 'properties': {
        'controls': {'type': 'array', 'items': {'type': 'object', 'properties': {'index': {'type': 'integer'}}}}}}}
    parts = object_blocks.select(SOURCE_ROOT, request)
    assert {'control.references', 'shared.registration', 'control.identity'} <= ids(request)
    assert len(parts) == len({p['path'] for p in parts})


def test_closed_arrays_stay_closed_inside_correction_but_other_branches_survive():
    closed = {'type': 'object', 'properties': {'shared_instances': {'type': 'array', 'maxItems': 0,
               'items': {'type': 'object', 'properties': {'knowledge': {'type': 'string'}}}}}}
    original = {'role': 'task_proposal', 'response_schema': closed}
    wrapped = {'role': 'step_correction', 'original_request': original,
               'response_schema': {'properties': {'proposal': {'anyOf': [closed, {'type': 'null'}]}}}}
    assert ids(wrapped) == ids(original)
    assert 'region.shared_instances' not in ids(wrapped)
    opened = deepcopy(closed);opened['properties']['shared_instances'].pop('maxItems')
    wrapped['response_schema']['properties']['proposal']['anyOf'].append(opened)
    assert 'region.shared_instances' in ids(wrapped)


def test_guard_fields_do_not_enable_rules_but_conditional_output_fields_do():
    schema = {'allOf': [{'if': {'properties': {'knowledge': {'type': 'string'}}},
                        'then': {'properties': {'findings': {'type': 'array', 'items': {'type': 'string'}}}}}]}
    selected = ids({'role': 'observation_update', 'response_schema': schema})
    assert 'task.findings' in selected and 'control.knowledge_revision' not in selected


def test_completion_and_knowledge_rules_follow_actual_output_capabilities():
    schema = {'properties': {'action': {'enum': ['click']}}}
    request = {'role': 'action_selection', 'response_schema': schema}
    assert not {'action.complete', 'action.none', 'task.completion'} & ids(request)
    schema['properties']['action']['enum'].extend(['complete', 'none'])
    assert {'action.complete', 'action.none', 'task.completion'} <= ids(request)
    schema = {'properties': {'knowledge': {'type': 'array', 'items': {'properties': {'description': {'type': 'string'}}}}}}
    request = {'role': 'observation_update', 'response_schema': schema}
    assert not {'control.knowledge_revision', 'control.knowledge_constraints'} & ids(request)
    schema['properties']['knowledge']['items']['properties']['constraints'] = {'type': 'object'}
    assert 'control.knowledge_constraints' in ids(request) and 'control.knowledge_revision' not in ids(request)


def test_semantic_disclosure_removes_ledger_addresses_and_keeps_raw_source():
    request = build();before = deepcopy(request)
    sent = render(request);text = sent['user_prompt']
    for internal in ['a0005', 'a0010', 'source_call', 'source_field', 'update:0024', 'internal/after.png', 'index=0', 'c9001']:
        assert internal not in text
    assert '快捷键搜索输入框' in text and '尚未确认；投递成功不等于' in text
    assert '最近登记的区块状态（历史，非当前确认）' in text
    assert '没有已绑定的当前框' in text
    assert 'Ctrl+Q' in text and 'CTRL+A' in text
    assert request == before
    assert json.loads(history_disclosure.structured_text(sent)) == json.loads(before['user_prompt'])
    assert sent['identity_candidate'] == before['identity_candidate']
    assert sent['original_request']['control_indexes'] == before['original_request']['control_indexes']
    assert history_disclosure.project(sent) == sent
    assert render(history_disclosure.restore(sent))['user_prompt'] == text


def test_same_attempt_is_once_but_identical_different_attempts_remain_separate():
    request = build();value, _ = prompt_material.body(request)
    shown = prompt_material.view(value, request)['相关历史与已登记认识']
    assert len(shown['历史尝试（不代表本次执行）']) == 5
    assert len(shown['已登记规则']) == 5
    context = request['control_identity_pair']['context']
    context['实际尝试与来源']['a0011'] = deepcopy(context['实际尝试与来源']['a0005'])
    assert len(prompt_material.view(value, request)['相关历史与已登记认识']['历史尝试（不代表本次执行）']) == 6
    assert '当时动作前区块' not in json.dumps(shown, ensure_ascii=False)
    assert shown['历史尝试（不代表本次执行）'][1]['当时前景区块（动作前后相同）'] == [
        'Shortcuts 对话框标题栏', '快捷键列表区', '快捷键搜索输入区']


def test_conflicting_versions_and_failed_attribution_are_not_silently_overwritten():
    request = build();value, _ = prompt_material.body(request)
    value['直接相关历史']['a0005']['观察'] = '另一份记录说明文字未发送。'
    value['直接相关历史']['a0005'].update({'归属纠正': '原任务归属已撤销', '执行': 'failed'})
    shown = prompt_material.view(value, request)['相关历史与已登记认识']
    first = shown['历史尝试（不代表本次执行）'][0]
    assert '记录差异' in first and len(first['材料']) == 2
    assert first['材料'][1]['归属纠正'] == '原任务归属已撤销'
    assert first['材料'][1]['投递状态'] == 'failed'


def test_conditions_and_earlier_doubts_survive_fact_projection():
    context = {'constraints': {'one': {'description': '相同文字', 'conditions': ['只读']},
                               'two': {'description': '相同文字', 'conditions': ['可写']}},
               '历史观察中的不确定性': [{'uncertainty': '图中对象可能被遮挡', 'source_call': 'old'}]}
    shown = prompt_material.identity_history(context, {})
    assert len(shown['已登记规则']) == 2
    assert shown['历史疑点（未自动解除）'] == [{'疑点': '图中对象可能被遮挡'}]


def test_current_attempt_is_not_relabelled_as_completed_history():
    request = build();value, _ = prompt_material.body(request)
    event = deepcopy(value['直接相关历史']['a0009']);event['观察'] = '当前待核对观察'
    value['直接相关历史']['a0010'] = event
    request['control_identity_pair']['context']['实际尝试与来源']['a0010'] = event
    shown = prompt_material.view(value, request)
    assert len(shown['相关历史与已登记认识']['历史尝试（不代表本次执行）']) == 5
    assert shown['当前任务与本次操作']['本次动作已有记录（仍需核对）']['观察'] == '当前待核对观察'
    assert shown['当前任务与本次操作']['效果确认'].startswith('尚未确认')


def test_owner_state_is_separate_and_supplement_validation_is_not_promoted():
    job, request = example_case()
    request['original_request']['page_context']['history']['events']['a0004'] = {
        'region': 'r0009', 'control': 'c9002', '区块': '快捷键搜索输入区', '入口': '另一个控件',
        '观察': '标题改变', '已有身份核对': [{'结论': 'same', '依据': '同一对话框'}]}
    job['supplements'] = [{'source_call': 'later-call', 'image': 'later.png',
        'validation': {'status': 'pending'}, 'reply': {'uncertainties': ['输入框被遮挡，仍无法确认']}}]
    sent = render(review.attach(SOURCE_ROOT, job, request))
    assert '同区块的已接受状态依据' in sent['user_prompt']
    assert '另一个控件' in sent['user_prompt'] and '校验状态：尚未通过校验' in sent['user_prompt']
    assert 'later-call' not in sent['user_prompt'] and 'later.png' not in sent['user_prompt']


def test_refresh_and_recheck_use_the_same_disclosure_without_reexecution():
    request = build();sent = render(request)
    assert page_context.refresh(deepcopy(sent)) == sent
    job, _ = example_case()
    previous = {'control_identity': 'different', 'reason': '先前理由，仍待复核'}
    before = deepcopy((job, sent, previous))
    rechecked = review.recheck_request(SOURCE_ROOT, job, sent, previous, '核对新的统一规则')
    text = render(rechecked)['user_prompt']
    assert '先前身份判断（本次待复核）' in text and '先前理由，仍待复核' in text
    assert 'a0005' not in text and '登记页面组成与访问来路' not in text
    assert rechecked['identity_candidate'] == sent['identity_candidate']
    assert rechecked['screenshots'] == ['current.png', 'historical.png']
    assert (job, sent, previous) == before


def test_selection_keeps_all_candidates_and_their_required_output_handles():
    job, request = example_case()
    first = job.pop('control_identity_pair');second = deepcopy(first)
    second.update(control='c9002', ref='c9002', old_name='另一独立输入框')
    second['context']['name'] = '另一独立输入框'
    job['control_identity_candidates'] = [first, second]
    request['screenshots'] = ['current.png']
    q = review.attach(SOURCE_ROOT, job, request);sent = render(q)
    assert q['response_schema']['properties']['candidate']['enum'] == ['c9001', 'c9002', None]
    for text in ['快捷键搜索输入框', '另一独立输入框', 'c9001', 'c9002']:
        assert text in sent['user_prompt']
    assert 'a0005' not in sent['user_prompt']
    assert review.selected_pair(sent, {'candidate': 'c9002', 'reason': '场景依据'})['control'] == 'c9002'


def test_selection_uses_pair_after_frame_and_completed_candidate_from_two_frame_update():
    job, request = example_case()
    first = job.pop('control_identity_pair');second = deepcopy(first)
    second.update(control='c9002', ref='c9002', old_name='另一独立输入框')
    job['control_identity_candidates'] = [first, second]
    request['screenshots'] = ['before.png', 'current.png']
    request['original_request']['screenshots'] = ['before.png', 'current.png']
    completed = deepcopy(job['candidate'])
    completed['controls'][0]['description'] = '冻结提案的当前对象观察'
    job['registration_submission'] = {'request': deepcopy(request['original_request']), 'candidate': completed}
    job['registration_submission']['request']['screenshots'] = ['current.png']
    q = review.attach(SOURCE_ROOT, job, request)
    assert q['screenshots'] == q['image_refs'] == ['current.png']
    assert q['identity_candidate'] == completed
    assert q['original_request'] == job['registration_submission']['request']
    text = render(q)['user_prompt']
    assert '原动作后图（身份候选选择）' in text and '冻结提案的当前对象观察' in text
    value, _ = prompt_material.body(q)
    value['单图步骤待登记的候选观察']['description'] = '其他草稿'
    shown = prompt_material.identity_view(value, q)
    assert '其他草稿' not in json.dumps(shown, ensure_ascii=False)
    job['control_identity_candidates'][1]['current_frame'] = 'different-time.png'
    with pytest.raises(ValueError, match='同一原场景'):
        review.attach(SOURCE_ROOT, job, deepcopy(request))


@pytest.mark.parametrize('decision', ['same', 'different', 'uncertain'])
def test_disclosure_preserves_normal_reply_binding_and_candidate(decision):
    q = build();reply = {'control_identity': decision, 'reason': '仅用于程序合同检查的预设回复'}
    before = deepcopy(reply)
    assert review.compared_candidate(q, reply) == review.compared_candidate(render(q), reply)
    assert reply == before


def test_historical_frame_caption_retains_time_without_source_dump():
    request = build()
    assert 'source_call' not in request['frame_context']['historical.png']
    assert '历史对象原场景' in request['frame_context']['historical.png']
    assert request['control_identity_pair']['historical_evidence']['source_call'] == '0024'


def test_single_frame_observation_survives_as_a_proposal_and_frames_keep_their_times():
    job, request = example_case()
    job['candidate']['controls'][0].update(
        description='搜索按钮旁另有独立输入框，两者同时存在。',
        knowledge=[{'description': '只在当前弹层内筛选', 'conditions': ['弹层打开']}])
    text = render(review.attach(SOURCE_ROOT, job, request))['user_prompt']
    assert '原单图提案中的观察（待核对，尚未接受）' in text
    assert '两者同时存在' in text and '弹层打开' in text
    assert '原动作后图（身份复核）' in text
    assert '不保证与下面每条历史记录同一时点' in text
    assert '左、上、右、下；原图像素' in text


def test_foreground_only_supplement_and_rejection_reason_are_not_lost():
    job, request = example_case()
    job['supplements'] = [{'reply': {'foreground': {
        'description': '确认弹窗接管前景', 'evidence': '搜索框在遮罩下',
        'uncertainty': '无法确认底层对象', 'exception': 'blocking_popup',
        'recovery_handoff': '先处理确认弹窗'}, 'focus_presence': 'not_interactive',
        'regions': [], 'controls': []}, 'validation': {'status': 'rejected', 'error': {
            'errors': [{'path': '/private-field', 'expected': '缺少必要的前景说明', 'actual': 'raw'}]}}}]
    text = render(review.attach(SOURCE_ROOT, job, request))['user_prompt']
    for content in ['确认弹窗接管前景', '无法确认底层对象', '先处理确认弹窗',
                    '已被其他表面接管', '未通过校验', '缺少必要的前景说明']:
        assert content in text
    assert '/private-field' not in text


def test_supplement_relations_use_its_own_rows_without_borrowing_control_aliases():
    row = {'reply': {'regions': [{'name': '面板', 'parent_index': None},
                                {'name': '面板', 'parent_index': 0}],
                     'controls': [{'index': 0, 'description': '历史增量，没有名称和归属'},
                                  {'name': '新输入框', 'region_index': 1, 'description': '位于内层面板'}]},
           'validation': {'status': 'validated'}}
    shown = prompt_material.identity_supplement(row)
    regions = shown['观察提案']['观察到的区块']
    controls = shown['观察提案']['观察到的控件']
    assert len(regions) == 2 and regions[0]['名称'] != regions[1]['名称']
    assert regions[1]['包含它的区块'] == regions[0]['名称']
    assert controls[1]['所属区块'] == regions[1]['名称']
    assert '未附该调用的身份映射' in controls[0]['引用限制']
    assert '名称' not in controls[0] and 'index' not in controls[0]
    assert '不代表已登记为事实' in shown['校验状态']


@pytest.mark.parametrize('regions,controls', [(None, []), ([None], [None]), ([], None)])
def test_schema_rejected_supplement_can_still_be_read(regions, controls):
    row = {'reply': {'regions': regions, 'controls': controls,
                     'foreground': {'uncertainty': '本次观察仍不能确定前景'}},
           'validation': {'status': 'rejected', 'error': '对象数组结构不合法'}}
    shown = prompt_material.identity_supplement(row)
    assert '未通过校验' in shown['校验状态']
    assert shown['校验问题'] == '对象数组结构不合法'
    text = json.dumps(shown, ensure_ascii=False)
    assert '材料限制' in text and '本次观察仍不能确定前景' in text


def test_shared_and_observation_only_knowledge_keep_distinct_limitations():
    context = {'关联任务': [{'name': '功能探索', 'status': 'done',
        'knowledge': [{'description': '切换静音', 'conditions': ['通话中'],
                       'constraints': {'limit': {'description': '仅影响当前通话'}}}],
        'knowledge_source': {'basis': 'identity_merge', 'sources': [
            {'basis': 'observation_only', 'shared': True, 'local_execution': False, 'source_call': 'private'},
            {'basis': 'explored'}]}, 'completion_basis': {'basis': 'observation_only'}}]}
    task = prompt_material.identity_history(context, {})['关联问题'][0]
    assert task['已有任务认识'][0]['适用条件'] == ['通话中']
    assert task['已有任务认识'][0]['已登记规则'][0]['说明'] == '仅影响当前通话'
    assert any('不表示已在本地执行' in note for note in task['知识使用限制'])
    assert any('部分依据' in note for note in task['知识使用限制'])
    assert task['任务完成依据限制'] == ['按观察记录，未声称执行']
    assert 'private' not in json.dumps(task)


def test_current_other_task_keeps_knowledge_prerequisite_and_preparation_purpose():
    job, request = example_case()
    source = json.loads(request['original_request']['user_prompt'])
    source['当前任务'] = {'task': 'r0010/原问题', 'control': 'c9010', 'control_name': '导出按钮',
        'task_type': 'function', '当前控件知识': [{'description': '导出当前页', 'conditions': ['已保存']}],
        '目标已知知识': [{'description': '必须有文件名', 'conditions': []}],
        'blocker': {'reason': '文件尚未命名'},
        'prerequisite': {'region': 'r0010', 'control': 'c9010', 'condition': '输入文件名', 'permitted': '填写名称'},
        '任务补充': {'说明': '本次仅为导出建立前提'}}
    request['original_request']['user_prompt'] = json.dumps(source, ensure_ascii=False)
    request['original_request']['page_context']['history']['names']['r0010'] = '导出区'
    text = render(review.attach(SOURCE_ROOT, job, request))['user_prompt']
    for content in ['导出按钮', '导出当前页', '已保存', '必须有文件名', '文件尚未命名',
                    '输入文件名', '填写名称', '本次仅为导出建立前提', '导出区']:
        assert content in text
    assert 'c9010' not in text


def test_per_step_targets_and_failed_text_delivery_survive():
    rows = prompt_material.identity_steps([
        {'action': 'click', 'target': '展开按钮', 'x': 0, 'y': 12},
        {'action': 'input_text', 'control': 'c9001', 'text': 'aA', 'text_delivered': False},
        {'action': 'wait', 'seconds': 2},
        {'action': 'click', 'target': 'r0009/c9001'}], {'r0009': '搜索区', 'c9001': '输入框'})
    assert rows[0]['操作目标'] == '展开按钮' and rows[0]['x'] == 0
    assert rows[1]['对象'] == '输入框' and rows[1]['文字投递'] == '未发送' and rows[1]['文本'] == 'aA'
    assert rows[2]['秒'] == 2
    assert rows[3]['操作目标'] == '搜索区 / 输入框'
    event = prompt_material.identity_event({'region': 'r0009', '区块': '搜索区', 'task': 'r0010/功能探索'},
                                           names={'r0010': '导出区'})
    assert event['原任务所属区块（不同于实际操作区块）'] == '导出区'
    job, request = example_case()
    source = json.loads(request['original_request']['user_prompt'])
    source['回执'].update(exit_code=None, text_delivered=False, description='全选失败，未发送文字')
    request['original_request']['user_prompt'] = json.dumps(source, ensure_ascii=False)
    text = render(review.attach(SOURCE_ROOT, job, request))['user_prompt']
    assert '投递结果尚未确认' in text and '全选失败，未发送文字' in text
