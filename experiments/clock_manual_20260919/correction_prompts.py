"""Select correction guidance from stage, structured diagnostics and evidence.

This is prompt composition only: acceptance and repair capabilities stay in
repair_stages. Unknown older diagnostics retain stage-level record guidance.
"""
import json
from pathlib import Path

RECORD_CODES={'duplicate_submission','duplicate_binding','existing_control_conflict',
              'list_representative','task_owner','inventory_coverage'}
OWNER_CODES={'owner','control_owner_surface','duplicate_control_owner','region_ownership_review',
             'parent_region','parent_cycle'}


def current_parse_failure(job):
    return job.get('blocked_by')=='model_response_parse_error' and job.get('candidate') is None


def parse_disclosure(job):
    """Expose current parsing state without rewriting retained failure evidence."""
    current=current_parse_failure(job)
    detail=job.get('parse_failure')
    parsed=job.get('candidate') is not None
    disclosed={
        '框架错误分类':('review_required' if parsed and job.get('blocked_by')=='model_response_parse_error'
                    else job.get('blocked_by','none')),
        '当前候选解析状态':('当前候选已解析，仍需修正当前校验诊断指出的内容错误。'
                       if parsed else '当前没有可解析候选。' if current else '本轮未提供候选回复。'),
    }
    if current and detail:
        disclosed['当前模型回复解析错误']=detail
    # Prior raw failures stay in the episode audit, not the next model context.
    return disclosed



def select(job, context):
    report=job.get('error')
    if isinstance(report,str):
        try:report=json.loads(report)
        except ValueError:report={}
    if not isinstance(report,dict):report={}
    codes={row.get('code') for row in report.get('errors',[]) if isinstance(row,dict)}
    modules=[];stage=job['stage'];q=job['request']
    # parse_failure is retained audit evidence, not the current failure type.
    if current_parse_failure(job):
        modules.append('回复解析')
        if not codes or codes<={'schema'}:return modules
    if stage=='action' or job.get('blocked_by') in ('binding_conflict','control_not_visible'):
        modules.append('定位绑定')
    if stage in ('discovery','update'):modules.append('身份名称')
    if stage in ('discovery','task_proposal'):modules.append('任务归属')
    if stage in ('update','task_result_review','function_registration'):modules.append('结果证据')
    if codes & RECORD_CODES or (not codes and stage!='action'):modules.append('登记修订')
    if codes & OWNER_CODES or job.get('blocked_by')=='region_ownership_review' or (not codes and stage in ('discovery','update')):
        modules.append('区块归属')
    if q.get('action_owner_candidates'):modules.append('动作归属')
    if context.get('最近尝试原始证据'):modules.append('重复无进展')
    return list(dict.fromkeys(modules))


def parts(root, job, context):
    names=['步骤纠正',*select(job,context)]
    return [{'path':'纠错/'+name+'.prompt','text':(Path(root)/'遍历prompt/纠错'/(name+'.prompt')).read_text()}
            for name in names]
