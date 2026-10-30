"""Offline prompt-contract fixtures, never screenshots or native Luna evidence.

Most schemas come from production builders. Small inline-only contracts are
copied explicitly where no schema constructor exists. All supplied facts are
illustrative. No model or GUI is called.
"""
from copy import deepcopy
import json
from pathlib import Path


RECORDS = {'r0001': {
    'id': 'r0001', 'name': '文档编辑区', 'description': '编辑文档并选择导出方式。',
    'controls': {
        'c0001': {'name': '导出按钮', 'knowledge': [{'description': '打开文档导出面板。'}]},
        'c0002': {'name': '格式选择框', 'knowledge': [{'description': '选择导出格式。'}]},
    },
    'tasks': {'查看可选格式': {'name': '查看可选格式', 'control': 'c0002',
        'task_type': 'parameter', 'status': 'pending', 'reason': '确认可选择的导出格式。',
        'attempts': []}},
}}
SCOPE = '探索示例文档应用的主要功能。'


def fixture_run(run, *, dependency=False):
    from regrow.records.object_store import Records, save
    from regrow.records.snapshots import write_json
    records = Records(deepcopy(RECORDS))
    if dependency:
        from regrow.records.object_store import owned_tasks
        task = owned_tasks(records['r0001'])['查看可选格式']
        task.update(status='blocked', blocker={'condition': 'prerequisite'})
        task['prerequisite'] = {'region': 'r0001', 'control': 'c0001',
            'condition': '导出面板已经打开', 'preparation': '打开导出面板',
            'evidence': '本离线例子中的已知准备条件。', 'permitted': True}
    run = Path(run)
    snapshot = run / 'knowledge_snapshots/fixture'
    snapshot.mkdir(parents=True, exist_ok=True)
    save(records, snapshot, write_json)
    write_json(snapshot / 'runtime_state.json', {'working_region': 'r0001',
        'interactive_regions': ['r0001'], 'observation': {'id': 'offline', 'control_refs': ['c0001', 'c0002']}})
    write_json(run / 'knowledge_current.json', {'snapshot': 'knowledge_snapshots/fixture'})
    write_json(run / 'run_manifest.json', {'exploration_scope': SCOPE})
    return records


def common(root, role, schema, material=None, kind=None):
    from regrow.prompts.compose import parts
    fixed = parts(root, role)
    text = json.dumps(material or {'离线示例': '以下事实只用于检查提示词组合。'}, ensure_ascii=False, indent=2)
    return {'role': role, 'stage': role, 'platform': 'android',
        'response_schema': schema, 'fixed_parts': fixed,
        'system_prompt': '\n\n'.join(p['text'] for p in fixed),
        'user_prompt': text, 'dynamic_prompt': text, 'screenshots': [],
        'work_context': {'kind': kind or role, 'region': 'r0001'},
        'source': {'region': 'r0001'}, 'run_scope': SCOPE}


def action(root, *, navigate=False, desktop=False):
    from regrow.runtime.action_commands import schema, selection_schema, platform_request
    from regrow.records.object_knowledge import fields
    from regrow.records.function_updates import schema as function_schema
    value = schema()
    if navigate:
        value['properties']['operation']['anyOf'] = [b for b in value['properties']['operation']['anyOf']
            if 'task_update' not in b.get('properties', {})]
    value = selection_schema(value)
    if not navigate:
        edits = fields(RECORDS, ['r0001'])
        edits['function_updates'] = function_schema(['r0001'])
        for branch in value['anyOf']:
            if {'complete', 'none'}.intersection(branch['properties']['action']['enum']):
                branch['properties'].update(deepcopy(edits))
    q = common(root, 'action_selection', value, {
        '当前目标': '到达导出面板' if navigate else '确认导出格式',
        '相关对象': [{'ref': 'r0001', 'name': '文档编辑区'}, {'ref': 'c0001', 'name': '导出按钮'}],
        '已知用途': '导出按钮打开导出面板。'}, 'navigate' if navigate else 'action')
    if not navigate:
        q['source'].update(task_name='查看可选格式', task_region='r0001', task_control='c0002')
    return platform_request(q, 'desktop' if desktop else 'android')


def proposal(root, *, old_tasks=False, shared=True):
    from regrow.traversal.task_proposer import proposal_schema
    from regrow.records.object_knowledge import fields
    from regrow.records.function_updates import schema as function_schema
    value = proposal_schema()
    value['properties'].update(fields(RECORDS, ['r0001']))
    value['properties']['function_updates'] = function_schema(['r0001'])
    value['properties']['operations']['items']['properties']['control']['enum'] = ['c0001', 'c0002', '']
    if old_tasks:
        value['properties']['task_update']['items']['properties']['task']['enum'] = ['r0001/查看可选格式']
    else:
        value['properties'].pop('task_update')
    if shared:
        item = value['properties']['shared_instances']['items']['properties']
        item['control']['enum'] = item['source_control']['enum'] = ['c0001', 'c0002']
        item['source_region']['enum'] = ['r0001']
    else:
        value['properties'].pop('shared_instances')
        value['required'].remove('shared_instances')
    return common(root, 'task_proposal', value, {'当前区块': 'r0001',
        '给定控件': [{'ref': cid, **row} for cid, row in RECORDS['r0001']['controls'].items()],
        '已有任务': ['r0001/查看可选格式'] if old_tasks else []}, 'task_proposal')


def object_registration(root, *, grounding=False):
    from regrow.traversal.object_registration import request, missing
    candidate = {'regions': [{'ref': 'r0001', 'name': '搜索区', 'description': '按名称查找条目。'}],
        'controls': [{'name': '搜索输入框', 'description': '带搜索标签的输入区域。', 'region_index': 0}]}
    original = {'screenshots': ['OFFLINE_NO_IMAGE.png'], 'source': {'region': 'r0001'}}
    details = {'/controls/0': {'name': '搜索输入框', 'state': '空白输入框，左侧有搜索图标。'}} if grounding else None
    return request(root, original, candidate, missing(candidate), grounding=details)


def observation(root, *, local=False, completion=False):
    from regrow.recognition.locator import schema
    from regrow.recognition.discovery_completion import extend_schema
    value = schema(root, 'local' if local else 'global', focus_present=local)
    if completion:
        extend_schema(value)
    q = common(root, 'observation', value, {'相关区块': 'r0001', '相关控件': ['c0001', 'c0002']})
    q['stage'] = 'discovery'
    q['discovery_context'] = {'mode': 'local' if local else 'global', 'focus': 'r0001' if local else None,
        'control_names': {'c0001': 'c0001', 'c0002': 'c0002'}}
    return q


def update(root, *, tasks=True, functions=True):
    from regrow.traversal.result_updater import build_update_request
    from regrow.records.function_updates import schema as function_schema
    q = build_update_request(root, {'已知区块': [{'ref': 'r0001'}],
        '任务更新引用': ['r0001/查看可选格式'] if tasks else [],
        '实际动作': [{'action': 'click', 'target': 'c0001'}]}, [])
    if functions:
        q['response_schema']['properties']['function_updates'] = function_schema(['r0001'])
    q['source'] = {'region': 'r0001', 'control': 'c0001'}
    return q


def review(root, *, result=False, coverage=False):
    from regrow.records.task_updates import schema
    from regrow.records.object_knowledge import fields
    item = schema(['parameter'])
    item['properties'].pop('task')
    item['required'].remove('task')
    value = {'type': 'object', 'properties': {'task_update': item, **fields(RECORDS, ['r0001'])},
        'required': ['task_update'], 'additionalProperties': False}
    if result:
        old = json.loads((Path(root) / 'regrow/prompts/输出格式/动作后更新.schema').read_text())
        value['properties']['action_result'] = old['properties']['action_result']
        value['required'].append('action_result')
    if coverage:
        fields = {'candidate': {'type': 'integer'}, **{
            key: {'type': 'string'} for key in ('evidence', 'condition', 'unverified')}}
        value['properties']['coverage'] = {'anyOf': [{'type': 'null'}, {
            'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}]}
        value['required'].append('coverage')
    return common(root, 'task_result_review', value, {'本轮任务': '查看可选格式',
        '说明': '没有执行新动作；核对已提供的事实。'})


def correction(root, original, *, sparse=False, record_edits=True, stage=None):
    from regrow.traversal.step_repair import request
    q = deepcopy(original)
    # Symbolic path opens the actual record-edit contract. It is never read,
    # displayed as an image or presented as real evidence.
    q['screenshots'] = ['OFFLINE_NO_IMAGE.png'] if record_edits else []
    stage = stage or ('update' if sparse else 'discovery')
    q['stage'] = stage
    job = {'stage': stage, 'request': q, 'record_edit': True, 'history': [],
        'candidate': {'uncertainties': ['需补充当前事实。']} if sparse else None,
        'error': {'errors': [{'code': 'existing_control_conflict', 'message': '离线组合例子。'}]}}
    result = request(root, job, {})
    return result


def without_images(q):
    q = deepcopy(q)
    q['screenshots'] = []
    q['image_refs'] = []
    return q


def cases(root, run):
    from regrow.traversal.region_functions import request_schema
    from regrow.recognition.appearance_comparison import request as appearance_request
    from regrow.recognition.action_target_review import request as target_request
    from regrow.recognition.ownership_review import request as ownership_request
    from regrow.records.shared_control_review import correction_request
    from regrow.traversal.recovery import build_request
    from regrow.runtime.model_transport import prepare_request
    records = fixture_run(run)
    items = {
        '01_observation_global': observation(root),
        '02_task_proposal_new': proposal(root),
        '03_action_selection_task': action(root),
        '04_observation_update': update(root),
        '05_object_registration': object_registration(root),
        '06_task_result_review': review(root),
        '07_function_registration': common(root, 'function_registration', request_schema(root, records['r0001'], records)),
    }
    original = deepcopy(items['04_observation_update'])
    original['screenshots'] = ['OFFLINE_CURRENT.png']
    items['08_appearance_comparison'] = appearance_request(root, run, original, 'OFFLINE_HISTORY.png', [{
        'ref': 'c0001', 'name': '播放按钮', 'historical_box': {'left': 10, 'top': 20, 'right': 40, 'bottom': 50},
        'description': '三角形播放图标', 'proposed_state': '两条竖线暂停图标'}])
    items['09_action_target_review'] = target_request(root, {'request': items['03_action_selection_task'],
        'candidate': {'action': 'click', 'target': 'c0001', 'x': 20, 'y': 30, 'reason': '查看导出面板。'},
        'action_target_doubt': {'reason': '待核对目标位置。'}})
    items['10_ownership_review'] = ownership_request(root, run, {
        'source_region': 'r0001', 'proposed_regions': [], 'assignments': {}, 'conflicts': {}, 'actions': []}, 'OFFLINE_NO_IMAGE.png')
    shared = common(root, 'shared_control_review', {'type': 'null'}, {'待核对共享关系': 'c0001 与 c0002 的用途差异。'})
    items['11_shared_control_review'] = correction_request(root, {'request': shared})
    items['12_recovery'] = build_request(root, {'actions': []}, '示例应用', '文档编辑区',
        {'exception': 'blocking_popup', 'evidence': '离线恢复合同例子。'}, 'OFFLINE_NO_IMAGE.png')
    # These inline contracts have no separately callable schema constructor.
    items['13_control_identity_selection'] = common(root, 'control_identity_selection', {
        'type': 'object', 'properties': {'candidate': {'type': ['string', 'null'], 'enum': ['c0001', None]},
        'reason': {'type': 'string', 'minLength': 1}}, 'required': ['candidate', 'reason'], 'additionalProperties': False})
    items['14_control_identity_comparison'] = common(root, 'control_identity_comparison', {
        'type': 'object', 'properties': {'control_identity': {'type': 'string', 'enum': ['same', 'different', 'uncertain']},
        'reason': {'type': 'string', 'minLength': 1}}, 'required': ['control_identity', 'reason'], 'additionalProperties': False})
    from regrow.traversal.repair_stages import update_observation_request
    items['15_step_observation'] = update_observation_request(root, run, {
        'request': items['04_observation_update'], 'attempt': 'offline-example',
        'observation_question': '格式菜单当前是否仍在前景？'}, 'OFFLINE_NO_IMAGE.png')
    items['16_branch_correction'] = common(root, 'branch_correction', {
        'type': 'object', 'properties': {'decision': {'type': 'string', 'enum': ['switch', 'stop']},
        'next_region': {'type': ['string', 'null'], 'enum': ['预览区', None]}, 'reason': {'type': 'string'}},
        'required': ['decision', 'next_region', 'reason'], 'additionalProperties': False})
    prepared = prepare_request(root, run, deepcopy(items['01_observation_global']))
    items['17_step_correction_full'] = correction(root, prepared)
    items.update({
        '18_navigation_android': action(root, navigate=True),
        '19_navigation_desktop': action(root, navigate=True, desktop=True),
        '20_task_proposal_existing': proposal(root, old_tasks=True, shared=False),
        '21_object_grounding': object_registration(root, grounding=True),
        '22_observation_local_completion': observation(root, local=True, completion=True),
        '23_update_without_tasks_functions': update(root, tasks=False, functions=False),
        '24_review_result_coverage': review(root, result=True, coverage=True),
        '25_recovery_desktop': build_request(root, {'actions': []}, '示例应用', '文档编辑区',
            {'exception': 'external_app', 'evidence': '离线恢复合同例子。'}, 'OFFLINE_NO_IMAGE.png'),
    })
    items['25_recovery_desktop']['platform'] = 'desktop'
    items['26_branch_resume'] = deepcopy(items['16_branch_correction'])
    items['26_branch_resume']['response_schema']['properties']['decision']['enum'].append('resume')
    items['27_target_navigation'] = target_request(root, {'request': items['18_navigation_android'],
        'candidate': {'action': 'click', 'target': 'c0001', 'x': 20, 'y': 30, 'reason': '到达导出面板。'},
        'action_target_doubt': {'reason': '待核对目标位置。'}})
    prepared_update = prepare_request(root, run, deepcopy(items['04_observation_update']))
    items['28_step_correction_sparse'] = correction(root, prepared_update, sparse=True)
    items['29_step_correction_no_edit'] = correction(root, prepared, record_edits=False)
    from regrow.traversal.correction_prompts import original_reply
    items['30_original_format_retry'] = original_reply(root, {'stage': 'discovery', 'request': prepared,
        'candidate': {'regions': [], 'controls': []}, 'error': {'errors': [{'code': 'schema', 'message': '缺少必填字段。'}]}})
    items['31_closed_knowledge_lists'] = deepcopy(items['02_task_proposal_new'])
    for name in ('controls', 'regions', 'function_updates'):
        items['31_closed_knowledge_lists']['response_schema']['properties'][name]['maxItems'] = 0
    items['32_correction_special_rules'] = deepcopy(items['17_step_correction_full'])
    part = {'path': '纠错/投递前画面变化.prompt', 'text': '离线专用规则：保留本次额外核对要求。'}
    items['32_correction_special_rules']['fixed_parts'].append(part)
    items['32_correction_special_rules']['system_prompt'] += '\n\n' + part['text']
    migration = deepcopy(prepared)
    migration['action_owner_candidates'] = [{'attempt': 'offline-example'}]
    migration['control_observation_candidates'] = [{'source_call': 'offline-example'}]
    items['33_correction_record_variants'] = correction(root, migration)
    prepared_object = prepare_request(root, run, without_images(items['05_object_registration']))
    prepared_appearance = prepare_request(root, run, without_images(items['08_appearance_comparison']))
    items['34_object_correction_permissions'] = correction(root, prepared_object, stage='object_registration')
    items['35_appearance_correction_permissions'] = correction(root, prepared_appearance, stage='appearance_comparison')
    historical = deepcopy(items['01_observation_global'])
    historical['fixed_parts'] = [{'path': '原步骤保存规则', 'text': '已保存的历史调用要求：按当时给定的对象范围作答。'}]
    historical['system_prompt'] = historical['fixed_parts'][0]['text']
    items['36_historical_saved_contract'] = correction(root, historical)
    dependency_run = Path(run) / 'with_dependencies'
    fixture_run(dependency_run, dependency=True)
    from regrow.traversal.task_prerequisites import augment
    items['37_observation_dependencies'] = augment(root, dependency_run, observation(root))
    items['38_update_dependencies'] = augment(root, dependency_run, update(root))
    items['39_task_scope_review'] = proposal(root, old_tasks=True, shared=False)
    items['39_task_scope_review']['work_context']['kind'] = 'scope_review'
    return {name: without_images(q) for name, q in items.items()}
