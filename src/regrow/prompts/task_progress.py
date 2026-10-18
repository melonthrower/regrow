from regrow.records.tasks import in_scope as _record_in_scope
from regrow.records.tasks import effective_task as _record_effective_task
'Render task progress; compatibility entry delegates to the single scheduler.'
from regrow.records.object_store import owned_tasks

def render_current(records, state, current_task=None):
    from regrow.records.tasks import coverage
    lines = []
    for rid in dict.fromkeys(state.get('interactive_regions', [])):
        if rid not in records:
            continue
        region = records[rid]
        c = coverage(region, records)
        lines.append(region['name'] + '：' + '；'.join((label + str(len(c[key])) for (key, label) in (('done', '已登记探索信息 '), ('record_only', '仅记录 '), ('blocked', '受阻 '), ('pending', '待完成 ')))))
    return '\n'.join(lines) + '\n本轮任务及其相关尝试见任务卡；其余任务由框架保留并调度。'

def render(region, records=None, *, include_history=True, current_task=None):
    from regrow.records import history_context as _task_attempt_context
    from regrow.records import shared_controls as _shared_controls
    from regrow.records.tasks import coverage
    records = records if records is not None else {region['id']: region}
    describe = _task_attempt_context.attempts
    lines = [region['name'] + '：探索任务']
    lines.extend(_shared_controls.render(records, region['id']))
    c = coverage(region, records)
    for name in owned_tasks(region):
        if not _record_in_scope(region, owned_tasks(region)[name], records):
            lines.append(f'- {name}：本轮范围外，保留历史记录')
            continue
        if owned_tasks(region)[name].get('coverage_exemption'):
            e = owned_tasks(region)[name]['coverage_exemption']
            lines.append('- ' + name + '：免重复探索（非执行完成）' + '；' + e['evidence'] + '；未验证：' + e['unverified'])
            continue
        status = '探索信息已登记（依据见任务记录）' if name in c['done'] else '仅记录' if name in c['record_only'] else '受阻' if name in c['blocked'] else '待完成'
        label = '本轮当前任务（定义见任务卡）' if current_task == {'region': region['id'], 'name': name} else name
        lines.append(f'- {label}：{status}')
        if include_history and name not in c['record_only']:
            task = owned_tasks(region)[name]
            effective = _record_effective_task(owned_tasks(region), task)
            lines.extend(('  ' + fact for fact in describe(effective, records)))
    return '\n'.join(lines)
