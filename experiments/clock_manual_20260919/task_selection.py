"""Render task progress; compatibility entry delegates to the single scheduler."""


def attach(root, records, state, working, base):
    from traversal_scheduler import select_work
    from action_proposer import render_work
    return render_work(root, records, state, select_work(records, state, working))


def render_current(records,state,current_task=None):
    return '\n\n'.join(render(records[rid],records,include_history=False,current_task=current_task) for rid in dict.fromkeys(state.get('interactive_regions',[])) if rid in records)



def render(region,records=None,*,include_history=True,current_task=None):
    from region_tasks import helper, coverage
    records=records if records is not None else {region["id"]:region}
    describe=helper("task_attempt_context").describe
    lines=[region['name']+'：探索任务']
    lines.extend(helper('shared_controls').render(records,region['id']))
    c=coverage(region,records)
    for name in region.get('tasks',{}):
        if not helper('task_prerequisites').in_scope(region,region['tasks'][name],records):
            lines.append(f'- {name}：本轮范围外，保留历史记录')
            continue
        if region['tasks'][name].get('coverage_exemption'):
            e=region['tasks'][name]['coverage_exemption']
            lines.append('- '+name+'：免重复探索（非执行完成）'+'；'+e['evidence']+'；未验证：'+e['unverified'])
            continue
        status='已探索（结果见动作记录）' if name in c['done'] else '仅记录' if name in c['record_only'] else '受阻' if name in c['blocked'] else '待完成'
        label='本轮当前任务（定义见任务卡）' if current_task=={'region':region['id'],'name':name} else name
        lines.append(f'- {label}：{status}')
        if include_history and name not in c['record_only']:
            task=region['tasks'][name]
            effective=region['tasks'].get(task.get('equivalent_to'),task) if task.get('handling')=='equivalent' else task
            lines.extend('  '+fact for fact in describe(effective,records))
    return '\n'.join(lines)
