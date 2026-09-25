"""Reuse observed entry effects across task names without replaying the GUI."""


def known_entries(region,control,operation):
    if operation not in ('tap','click'):return []
    hits=[]
    for aid,action in region.get('actions',{}).items():
        if (action.get('control')!=control or action.get('operation') not in ('tap','click')
                or action.get('delivery')!='executed_receipt_zero'
                or action.get('text_delivered') is False
                or action.get('result',{}).get('exception')!='none'
                or action.get('result',{}).get('returns_to_previous') is True):continue
        targets=list(dict.fromkeys(action.get('interactive_regions',[])))
        if len(targets)!=1 or targets[0]==region['id']:continue
        hits.append({'attempt':aid,'destination_region':targets[0],
                     'description':action['result'].get('description','')})
    return hits


def reuse(region):
    """Single-action navigation is already known; target exploration stays separate."""
    reused=[]
    for name,task in region.get('tasks',{}).items():
        if task.get('deferral',{}).get('retry_when')in ('explicit_task_ownership_review','explicit_result_review'):continue
        if task.get('task_type')!='single_action' or task.get('handling')!='explore' or task.get('status')=='done':continue
        hits=known_entries(region,task.get('control'),task.get('action'))
        if not hits or len({h['destination_region'] for h in hits})!=1:continue
        task['status']='done'
        task['result_evidence']='入口直接结果已有记录：'+hits[-1]['description']+'；目的区块内部探索另行登记，不重复验证入口。'
        task['completion_basis']={'rule':'reuse_observed_entry','evidence':hits}
        task['attempts']=list(dict.fromkeys(task.get('attempts',[])+[h['attempt'] for h in hits]))
        reused.append(name)
    return reused


import importlib.util
from pathlib import Path

def history():
    spec=importlib.util.spec_from_file_location('history_context',Path(__file__).with_name('history_context.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def disclose(region,control,records):
    return history().disclose(region,control,records)

def related(region,control,records):
    return history().related(region,control,records)
