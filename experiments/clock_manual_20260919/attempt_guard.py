"""Repeated unsuccessful task attempts enter the existing correction boundary."""
import json
from pathlib import Path


class RepeatedAttempt(ValueError):
    blocked_by='review_required'


def check(run, records, binding, proposal, frame=None, *, correction=False):
    # Repeated input is only comparable on the same visible surface.
    if proposal.get('action') not in ('input_text','click','tap','double_click','back') or not frame:return
    from visual_backtrack import same_surface
    rid=binding.get('task_region',binding['region_ref']);name=binding.get('task_name')
    task=records.get(rid,{}).get('tasks',{}).get(name)
    if not task or task.get('status')!='pending':return
    repeated=[];navigation={};prior_points=[];corrected=False
    for attempt in task.get('attempts',[]):
        folder=Path(run)/'action_attempts'/attempt
        try:
            old=json.loads((folder/'proposal.json').read_text());owner=json.loads((folder/'binding.json').read_text())
        except (OSError,ValueError):continue
        if binding.get('control_ref') is None and (old.get('target'),old.get('x'),old.get('y'))!=(proposal.get('target'),proposal.get('x'),proposal.get('y')):continue
        same_action=(old.get('action')==proposal['action'] or {old.get('action'),proposal['action']}<= {'click','tap','double_click'})
        if same_action and (owner.get('region_ref'),owner.get('control_ref'),old.get('text'))==(binding['region_ref'],binding.get('control_ref'),proposal.get('text')):
            if same_surface(folder/'before.png',frame):
                corrected=corrected or owner.get('repeat_correction',False)
                prior_points.append((old.get('x'),old.get('y')))
                action=records.get(owner.get('region_ref'),{}).get('actions',{}).get(attempt,{})
                targets=tuple(sorted(set(action.get('interactive_regions',[]))))
                if (proposal['action']!='input_text' and action.get('delivery')=='executed_receipt_zero'
                        and action.get('result',{}).get('exception')=='none'
                        and not action.get('result',{}).get('returns_to_previous')
                        and action.get('destination_behavior')!='history_dependent' and proposal['action']!='back' and targets
                        and owner.get('region_ref') not in targets):
                    navigation.setdefault(targets,[]).append((attempt,action['result'].get('description','')))
                if proposal['action']=='input_text' or same_surface(folder/'after.png',frame):repeated.append(attempt)
    if len(repeated)>=2:
        if correction and not corrected and (proposal.get('x'),proposal.get('y')) not in prior_points:
            binding['repeat_correction']=True
            return
        raise RepeatedAttempt('同一未完成任务在相同界面已重复尝试同一入口，未取得目标进展：'+', '.join(repeated)+
            '。换同一控件内的点击位置不构成新依据。禁止原样再试；请observe确认新界面的实际目标，改用有新依据的入口/参数，或defer暂挂。命令成功不等于任务有进展。')

    for targets,history in navigation.items():
        if len(history)>=2:
            raise ValueError('重复导航未完成原任务：在与当前相同的起始画面，已两次通过同一入口到达相同区块。实际记录：'+
                '；'.join(a+'：'+description for a,description in history[-2:])+
                '。这些跳转本身已成功，但任务仍未完成；请依据任务历史选择能提供新证据的动作或改变验证条件，不能原样再走同一路径。确无可用验证办法时可defer并保留未确认结果。')
