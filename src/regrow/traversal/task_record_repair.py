from regrow.records.object_store import region_work
'Task judgment and owner corrections; executed evidence keeps its identity.'
from regrow.records.tasks import audit as task_audit
from regrow.records.tasks import read as task_value
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from copy import deepcopy
from pathlib import Path

def local_done(task):
    return bool(task and task.get('status') == 'done' and not any(task.get(k) for k in (
        'equivalent_to', 'coverage_exemption')))

def request(root, run, region, name, reason):
    """Build one explicit completed-task review from its real completion call."""
    from regrow.records.snapshots import load, read
    from regrow.records.calls import submission
    from regrow.records.tasks import detached
    from regrow.records.history_context import task_goal
    from regrow.traversal.work_context import select
    from regrow.prompts import frame_context
    from regrow.prompts.prompt_material import assign
    run = Path(run).resolve()
    if (run / 'execution_pending.json').exists():
        raise ValueError('先登记已执行动作，再复核指定的旧完成判断；不重投原动作')
    snapshot, records, state = load(run)
    task = owned_tasks(records.get(region, {})).get(name)
    if not local_done(task):
        raise ValueError('请指定本地已完成的原任务；共享任务回其规范来源复核')
    if not reason.strip():
        raise ValueError('请指出原完成判断的具体疑点')
    previous = task_value(task, 'latest_update', {})
    call = previous.get('source', {}).get('source_call') or task_value(task, 'completion_basis', {}).get('source_call')
    if not call or Path(call).name != call:
        raise ValueError('原任务缺少可追溯的完成调用，保留记录等待补齐原证据')
    original, reply = submission(run, call)
    from regrow.traversal.object_registration import semantic_revision
    original, reply = semantic_revision(original, reply)
    frames = [str((run / frame).resolve()) for frame in original.get('screenshots', [])]
    if not frames or any(not Path(frame).is_file() for frame in frames):
        raise ValueError('旧完成调用的原图缺失，不能凭结束摘要重开任务')
    frame_context.validate(original)
    primary = str((run / frame_context.primary(original)).resolve())
    work = select(records, state, 'task_proposal', region, task={'region': region, 'name': name}, reason=reason)
    # Use the ordinary complete Region/task/history builder, without asserting
    # that a saved completion frame is the current live scene.
    from regrow.traversal.task_proposer import plan_request
    q = plan_request(root, records, state, region, work=work, current_scene=False)
    q['source'].update(task_region=region, task_name=name, task_control=task.get('control'),
                       snapshot=str(snapshot.relative_to(run)))
    q['done_task_review'] = {'region': region, 'task': name,
        'snapshot': str(snapshot.relative_to(run)), 'before': detached(task),
        'completion_call': call, 'screenshots': frames, 'primary': primary}
    q.update(screenshots=frames, image_refs=list(frames))
    q['frame_context'] = {frame: frame_context.purpose(original, old)
                          for frame, old in zip(frames, original['screenshots'])}
    assign(q, {'指定复核原题': {'task': name, **detached(task)},
               '原题目标与实际过程': task_goal(task, records, run),
               '旧完成调用': {'call': call,
                    '保存的模型请求': read(run / 'calls' / call / 'request.json'),
                    '模型原答': read(run / 'calls' / call / 'response.json'),
                    '登记采用的语义请求': original, '登记采用的结果': reply},
               '本次具体疑点': reason})
    return q

def validate_review(run, job, edit, records):
    """Only the explicitly disclosed, unchanged task/evidence may be reopened."""
    from regrow.records.snapshots import load
    from regrow.records.tasks import detached
    case = job['request'].get('done_task_review')
    if not case or isinstance(edit, list):
        raise ValueError('重开任务需要明确给定的单项原题、旧判断与实际证据')
    snapshot = load(run)[0]
    if str(snapshot.relative_to(Path(run).resolve())) != case['snapshot']:
        raise ValueError('原题复核快照已变化，请重新提供原判断与证据')
    task = owned_tasks(records.get(case['region'], {})).get(case['task'])
    if not local_done(task) or detached(task) != case['before']:
        raise ValueError('指定的原题或完成判断已变化，不能沿用旧复核')
    if (edit.get('region'), edit.get('task'), edit.get('field'), edit.get('before')) != (
            case['region'], case['task'], 'reopen_task', task.get('control') or ''):
        raise ValueError('本次只可复核给定原题，保持原控件与原条件')
    frames = [str((Path(run) / frame).resolve()) for frame in job['request'].get('screenshots', [])]
    if frames != case['screenshots'] or any(not Path(frame).is_file() for frame in frames):
        raise ValueError('原完成图未完整保留，不能沿用本次复核')

def apply(region, state, edit, call):
    name = edit['task']
    task = owned_tasks(region).get(name)
    if task is None:
        raise ValueError('修订任务不存在：' + name)
    if not edit['evidence'].strip():
        raise ValueError('任务归属修订需要依据')
    old = task.get('control')
    control = owned_controls(region).get(old, {})
    if (old or '') != edit['before']:
        raise ValueError('任务原控件不匹配，请核对原记录')
    if edit['field'] == 'task_control':
        targets = [edit['after']] if edit['after'] in owned_controls(region) else []
        if len(targets) != 1:
            raise ValueError('新控件尚未登记或名称不唯一，先补发现')
        dependent = any((t.get('equivalent_to') == name for (n, t) in owned_tasks(region).items() if n != name))
        supported = any((name in f.get('task_refs', []) for f in region.get('functions', {}).values()))
        if task.get('status') != 'pending' or any((task_value(task, k) for k in ('attempts', 'findings', 'equivalent_to', 'completion_basis', 'result_evidence', 'blocker', 'deferral', 'blocker_history'))) or dependent or supported:
            raise ValueError('任务已有历史、结论或依赖，不能改挂；使用suspend_task保留旧记录，再提出正确控件的新任务')
        task['control'] = targets[0]
    elif edit['field'] == 'reopen_task':
        if not local_done(task):
            raise ValueError('仅复核给定的本地已结束原题；共享问题回其规范来源复核')
        if not edit['after'].strip():
            raise ValueError('reopen_task的after需要具体未知内容及观察目标')
        from regrow.records.tasks import detached
        previous = detached(task)
        previous.get('_task_audit', {}).pop('revisions', None)
        from regrow.records.task_updates import hard_block
        blocked = hard_block(task)
        status = 'blocked' if blocked else 'pending'
        audit = task_audit(task)
        audit.setdefault('revisions', []).append({'before': previous,
            'after': {'status': status, 'remaining_question': edit['after']},
            'evidence': edit['evidence'], 'source_call': call})
        if audit.get('latest_update'):
            audit.setdefault('update_history', []).append(audit['latest_update'])
        audit.pop('completion_basis', None)
        audit['latest_update'] = {'decision': 'defer' if blocked else 'continue',
            'remaining_question': edit['after'], 'reason': edit['evidence'],
            'source': {'source_call': call, 'basis': 'record_review'}}
        if blocked:
            audit['latest_update']['retry_when'] = task.get('deferral', {}).get('retry_when') or task.get('blocker', {}).get('condition')
        task['status'] = status
    elif edit['field'] == 'suspend_task':
        if edit['after']:
            raise ValueError('suspend_task的after留空，不迁移历史')
        task.update(status='blocked', blocker={'condition': 'review_required', 'source_call': call}, deferral={'reason': edit['evidence'], 'source_call': call, 'retry_when': 'explicit_task_ownership_review'})
        if state.get('active_task') == {'region': region['id'], 'name': name}:
            state.pop('active_task', None)
        region_work(region).setdefault('task_inventory', {})['review'] = {'kind': 'task_proposal', 'reason': '旧任务归属冲突已暂挂；给正确控件补建独立任务，不继承旧历史。' + edit['evidence'], 'source_call': call}
    else:
        raise ValueError('未知任务修订能力')
