"""Select correction guidance from stage, structured diagnostics and evidence.

This is prompt composition only: acceptance and repair capabilities stay in
repair_stages. Unknown older diagnostics retain stage-level record guidance.
"""
import json
RECORD_CODES = {'duplicate_submission', 'duplicate_binding', 'existing_control_conflict', 'list_representative', 'task_owner'}
OWNER_CODES = {'owner', 'control_owner_surface', 'duplicate_control_owner', 'region_ownership_review', 'parent_region', 'parent_cycle', 'local_region_bounds', 'local_control_owner', 'local_control_duplicate'}

def current_parse_failure(job):
    return job.get('blocked_by') == 'model_response_parse_error' and job.get('candidate') is None

def parse_disclosure(job):
    """Expose current parsing state without rewriting retained failure evidence."""
    current = current_parse_failure(job)
    detail = job.get('parse_failure')
    parsed = job.get('candidate') is not None
    disclosed = {'框架错误分类': 'review_required' if parsed and job.get('blocked_by') == 'model_response_parse_error' else job.get('blocked_by', 'none'), '当前候选解析状态': '当前候选已解析，仍需修正当前校验诊断指出的内容错误。' if parsed else '当前没有可解析候选。' if current else '本轮未提供候选回复。'}
    if current and detail:
        disclosed['当前模型回复解析错误'] = detail
    return disclosed

def select(job, context):
    report = job.get('error')
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except ValueError:
            report = {}
    if not isinstance(report, dict):
        report = {}
    codes = {row.get('code') for row in report.get('errors', []) if isinstance(row, dict)}
    modules = []
    stage = job['stage']
    q = job['request']
    if current_parse_failure(job):
        modules.append('回复解析')
        if not codes or codes <= {'schema'}:
            return modules
    if stage == 'action' or job.get('blocked_by') in ('binding_conflict', 'control_not_visible'):
        modules.append('定位绑定')
    if stage in ('discovery', 'update'):
        modules.append('身份名称')
    if stage in ('discovery', 'task_proposal') and q.get('screenshots'):
        modules.append('任务归属')
    if stage in ('update', 'task_result_review', 'function_registration'):
        modules.append('结果证据')
    if q.get('screenshots') and (codes & RECORD_CODES or (not codes and stage != 'action')):
        modules.append('登记修订')
    if q.get('screenshots') and (codes & OWNER_CODES or job.get('blocked_by') == 'region_ownership_review' or (not codes and stage in ('discovery', 'update'))):
        modules.append('区块归属')
    if stage != 'action' and q.get('action_owner_candidates'):
        modules.append('动作归属')
    if context.get('最近尝试原始证据'):
        modules.append('重复无进展')
    return list(dict.fromkeys(modules))

def parts(root, job, context):
    if job['stage'] == 'object_registration':
        from regrow.prompts.compose import load
        return load(root, ['纠错/对象识别资料.prompt'])
    names = ['步骤纠正', *select(job, context)]
    from regrow.prompts.compose import load
    from regrow.prompts.compose import sections
    from regrow.prompts.output import fields
    keys = fields(job['request']['response_schema'])
    result = load(root, ['纠错/' + name + '.prompt' for name in names])
    for part in result:
        if part['path'] == '纠错/步骤纠正.prompt' and (not job['request'].get('screenshots')):
            part['text'] = sections(part['text'], {'## 记录修订 → edit_record'})
        if part['path'] == '纠错/结果证据.prompt':
            conditions = {'## 原任务判断 → task_update': {'task_update'}, '## 已执行动作与旧区块 → action_result / previous_regions': {'action_result', 'previous_regions'}, '## 功能整理 → functions / local_knowledge': {'functions', 'local_knowledge'}}
            part['text'] = sections(part['text'], {heading for (heading, needed) in conditions.items() if not keys.intersection(needed)})
    return [part for part in result if part['text'].strip()]
