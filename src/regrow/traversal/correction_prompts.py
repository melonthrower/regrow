"""Select correction guidance from stage, structured diagnostics and evidence.

This is prompt composition only: acceptance and repair capabilities stay in
repair_stages. Unknown older diagnostics retain stage-level record guidance.
"""
import json
from copy import deepcopy


def needs_record_repair(job):
    """Keep existing observation/edit capabilities for record-level conflicts."""
    report = job.get('error')
    if not isinstance(report, dict):
        return False
    return any(row.get('code') in {'task_owner', 'existing_control_conflict',
        'unknown_candidate_control', 'region_ownership_review', 'control_owner_surface',
        'duplicate_control_owner'} for row in report.get('errors', []))


def original_reply(root, job):
    """Ask the original question again, using its sent contract and evidence."""
    from regrow.prompts.compose import load
    from regrow.prompts.correction_feedback import describe, organize
    from regrow.prompts.field_placeholders import fill_missing
    original = deepcopy(job['request'])
    rejected = deepcopy(job.get('rejected_reply', job.get('candidate')))
    if job['stage'] == 'update':
        from regrow.traversal.object_registration import semantic_revision
        original, rejected = semantic_revision(original, rejected)
    correction = deepcopy(original)
    from regrow.traversal.proposal_revision import prepare, guidance, display, examples, MODE
    base = prepare(job, original, correction['response_schema'])
    feedback = {'执行状态': '原动作已经执行，本次只修正结果登记。' if job.get('attempt') else '本步骤尚未执行动作。'}
    if base is not None:
        rejected = display(base)
        feedback['修订方式'] = guidance()
        feedback['局部修订格式示例'] = examples(base)
        if job.get('rejected_reply') is not None:
            _, feedback['未接受的局部修订'] = semantic_revision(original, job['rejected_reply'])
        from regrow.prompts.output import prepare as present
        correction = present(correction, root)
    if isinstance(job.get('error'), dict) and job['error'].get('unchecked'):
        feedback['尚未完成的检查'] = job['error']['unchecked']
    if job.get('parse_failure') and rejected is None:
        feedback['回复解析问题'] = job['parse_failure']
    if job.get('supplements'):
        feedback['补充观察'] = deepcopy(job['supplements'])
    if isinstance(job.get('error'), dict):
        rejected = fill_missing(root, rejected, job['error'], original['response_schema'])
    part = load(root, ['纠错/原格式重答.prompt'])[0]
    result = organize(root, correction, part, describe(job.get('error'), rejected, original), rejected, feedback)
    result.update(role='step_correction', stage='step_correction',
                  correction_format='original', original_request=original)
    if base is not None:
        result['proposal_base'] = base
        result['proposal_revision'] = MODE
    for key in ('_structured_user_prompt', '_presentation_digest'):
        result.pop(key, None)
    return result

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
    return list(dict.fromkeys(modules))

def parts(root, job, context):
    names = select(job, context)
    from regrow.prompts.compose import load
    from regrow.prompts.compose import sections
    from regrow.prompts.output import fields
    keys = fields(job['request']['response_schema'])
    result = load(root, ['纠错/' + name + '.prompt' for name in names])
    for part in result:
        if part['path'] == '纠错/结果证据.prompt':
            conditions = {'## 原任务判断 → task_update': {'task_update'}, '## 已执行动作的结果与前景': {'action_result', 'current_regions', 'previous_regions'}, '## 修正功能和区块用法': {'function_updates', 'local_knowledge'}}
            part['text'] = sections(part['text'], {heading for (heading, needed) in conditions.items() if not keys.intersection(needed)})
    return [part for part in result if part['text'].strip()]
