from regrow.records.snapshots import load as _record_load
from regrow.paths import SOURCE_ROOT
'One bounded Region task round: inventory if needed, action, update, then pause.'
import argparse
from pathlib import Path
from regrow.runtime.recover_external import RecoveryRun
from regrow.records.snapshots import read
from regrow.records.snapshots import write_json
from regrow.traversal import discovery_step as discovery_step
from regrow.traversal import recover_loop as recover_loop
from regrow.runtime import progress as progress
from regrow.traversal import step_repair as step_repair
from regrow.recognition import visual_backtrack as visual_backtrack
from regrow.traversal import exploration_loop as exploration_loop
from regrow.traversal.traversal_scheduler import Scheduler
from regrow.traversal.traversal_scheduler import pending_work
from regrow.traversal.traversal_scheduler import preview_next
from regrow.traversal.observation import Locator
from regrow.traversal.task_proposer import TaskProposer
from regrow.traversal.action_proposer import ActionProposer
from regrow.runtime.action_executor import ActionExecutor
from regrow.runtime.action_executor import foreground_window
from regrow.traversal.result_updater import ResultUpdater

def action_capacity_status(account):
    """Reserve selection+result; local progress can resume in the next small step."""
    if account['max_http'] - account['http_started'] >= 2:
        return None
    return 'ready_next_round' if account['http_started'] else 'budget_limit'

def _run_step(root, run, out, *, review_update=None, limits=None):
    from regrow.recognition import ownership_review as _ownership_review
    from regrow.traversal import suspended_updates as _suspended_updates
    from regrow.records import task_settlement as _task_settlement
    from regrow.records import shared_control_review as _shared_control_review
    (root, run, out) = (Path(root).resolve(), Path(run).resolve(), Path(out).resolve())
    out.mkdir(parents=True, exist_ok=False)
    manifest = read(run / 'run_manifest.json')
    if manifest.get('platform') == 'desktop':
        from regrow.runtime.desktop_transport import DesktopRun
        transport = DesktopRun.__new__(DesktopRun)
        transport.configure(manifest)
    else:
        transport = RecoveryRun.__new__(RecoveryRun)
    transport.root = root
    transport.run = run
    transport.ledger = out / 'budget.json'
    manifest = read(run / 'run_manifest.json')
    transport.device = manifest['device']
    transport.package = manifest['app']
    transport.account = {'max_http': 6, 'max_gui_commands': 6, **(limits or {}), 'http_started': 0, 'gui_started': 0, 'status': 'running'}
    transport.save()
    write_json(out / 'knowledge_before.json', read(run / 'knowledge_current.json'))
    selection_window = foreground_window(transport)
    write_json(out / 'selection_window.json', {'window': selection_window})
    transport.screenshot(out / 'current.png')
    calls = []

    def call(q):
        (ref, reply) = transport.call(q)
        calls.append(ref)
        return (ref, reply)
    repair = step_repair.Runner(root, run, call, transport.screenshot, lambda : transport.account['max_http'] - transport.account['http_started'], review_update=review_update)
    scheduler = Scheduler(root, run, out / 'current.png', out)
    locator = Locator(root, run, out / 'current.png', call, repair)
    proposer = ActionProposer(repair)
    executor = ActionExecutor(transport, out, repair)
    updater = ResultUpdater(root, transport, repair)

    def current():
        request = scheduler.current()
        if locator.locate_control(request):
            request = scheduler.current()
        return request
    if (run / 'ownership_review.json').exists():
        result = _ownership_review.run(root, transport, out, call)
        write_json(out / 'result.json', {**result, 'gui_actions': transport.account['gui_started']})
        transport.account['status'] = result['status']
        transport.save()
        return
    resumed = None
    _suspended_updates.restore_next(run, out / 'current.png')
    step_repair.reopen_blocked(run, out / 'current.png')
    work = pending_work(run)
    if work and work['kind'] == 'update':
        result = updater.resume(work)
        write_json(out / 'result.json', {**result, 'calls': calls, 'gui_actions': 0})
        transport.account['status'] = 'paused_after_update'
        transport.save()
        return
    if work:
        pending = work['pending']
        if pending.get('pre_dispatch_review') and pending['stage'] == 'action':
            frame = str(out / 'current.png')
            pending['pre_dispatch_review'].update(current=frame, window=selection_window)
            pending['request'].update(screenshots=[frame], image_refs=[frame])
            pending['history'].append({'observation': frame, 'reason': '投递前重新确认使用本轮新截图；原提案仍未执行'})
            repair.save(pending)
        resumed = repair.perform(pending['stage'])
        if resumed['stage'] in ('task_result_review', 'shared_control_review'):
            write_json(out / 'result.json', {'status': 'ready_next_round', 'calls': calls, 'gui_actions': 0, 'task_result_review': resumed['result']})
            transport.account['status'] = 'ready_next_round'
            transport.save()
            return
    state = _record_load(run)[2]
    if state.get('reason') in ('historical_update_registered', 'result_registration_deferred') and state.get('next_action_mode') == 'discover':
        discovery_step.await_discovery(run, str(out / 'current.png'), 'historical-update-' + out.name)
    navigation = visual_backtrack.resume_pending(transport, out / 'current.png')
    if navigation:
        write_json(out / 'result.json', {**navigation, 'calls': calls})
        return
    if not step_repair.pending(run) and (not (run / 'execution_pending.json').exists()):
        _task_settlement.reconcile_run(run)

    def route_recovery():
        if _record_load(run)[2].get('next_action_mode') not in ('recover', 'recover_scope', 'review_result'):
            return False
        result = recover_loop.run(root, transport, out, call, repair=repair)
        write_json(out / 'result.json', {**result, 'calls': calls})
        transport.account['status'] = result['status']
        transport.save()
        return True
    if route_recovery():
        return
    if _record_load(run)[2].get('next_action_mode') == 'discover':
        locator.discover()
        if route_recovery():
            return
    _shared_control_review.run_pending(repair)
    q = current()
    if q['stage'] == 'task_proposal':
        TaskProposer.run(repair, q)
        if _record_load(run)[2].get('next_action_mode') == 'discover':
            locator.discover()
            if route_recovery():
                return
        q = current()
        if q['stage'] == 'task_proposal':
            write_json(out / 'result.json', {'status': 'task_proposal', 'calls': calls, 'gui_actions': 0})
            transport.account['status'] = 'paused_after_rediscovery'
            transport.save()
            return
    if q['stage'] == 'function_registration':
        repair.perform('function_registration', q)
        q = current()
        if q['stage'] == 'function_registration':
            write_json(out / 'result.json', {'status': 'ready_next_round', 'calls': calls, 'gui_actions': 0})
            transport.account['status'] = 'ready_next_round'
            transport.save()
            return
    if q.get('stage') == 'task_result_review':
        reviewed = repair.perform('task_result_review', q)
        write_json(out / 'result.json', {'status': 'ready_next_round', 'calls': calls, 'gui_actions': 0, 'task_result_review': reviewed['result']})
        transport.account['status'] = 'ready_next_round'
        transport.save()
        return
    write_json(out / 'action_request.json', q)
    if not q['action_ready']:
        write_json(out / 'result.json', {'status': q['stage'], 'calls': calls, 'gui_actions': 0})
        transport.account['status'] = 'paused_' + q['stage']
        transport.save()
        return
    capacity = action_capacity_status(transport.account)
    if capacity:
        raise step_repair.Paused(capacity, '当前小步HTTP额度不足以选择动作并登记结果；未执行，保留原任务。已推进的小步可续接；无推进的尾段结束本批。')
    accepted = proposer.propose(q, resumed)
    result = accepted['result']
    q = result['request']
    ref = result['call']
    proposal = result['proposal']
    binding = result['binding']
    write_json(out / 'binding.json', binding)
    if transport.account['http_started'] >= transport.account['max_http']:
        raise step_repair.Paused('ready_next_round', '动作尚未执行，下一轮重新核对目标后继续')
    if binding['status'] == 'no_action':
        from regrow.traversal.traversal_scheduler import handoff_no_action
        handoff = handoff_no_action(run, q, proposal, ref, out / 'current.png')
        write_json(out / 'result.json', {'status': 'ready_next_round', 'calls': calls, 'gui_actions': 0, **handoff})
        transport.account['status'] = 'ready_next_round'
        transport.save()
        return
    if binding['status'] != 'matched':
        write_json(out / 'result.json', {'status': binding['status'], 'calls': calls, 'gui_actions': 0})
        transport.account['status'] = 'paused_' + binding['status']
        transport.save()
        return
    folder = executor.execute(accepted, selection_window, calls)
    if folder is None:
        return
    updated = updater.update(folder)
    (attempt, pointer) = (updated['attempt'], updated['pointer'])
    nextq = preview_next(root, run)
    write_json(out / 'next_request.json', nextq)
    write_json(out / 'result.json', {'status': 'updated', 'calls': calls, 'attempt': attempt, 'gui_actions': 1, 'pointer': pointer, 'next_stage': nextq['stage']})
    transport.account['status'] = 'paused_after_update'
    transport.save()

@progress.tracked
def run_step(root, run, out, *, review_update=None, limits=None):
    from regrow.runtime.model_transport import BudgetExhausted
    from regrow.runtime.reply_correction import Failed
    try:
        _run_step(root, run, out, review_update=review_update, limits=limits)
    except BudgetExhausted as error:
        out = Path(out)
        budget = read(out / 'budget.json')
        budget['status'] = 'budget_limit'
        write_json(out / 'budget.json', budget)
        write_json(out / 'result.json', {'status': 'budget_limit', 'reason': str(error), 'gui_actions': budget['gui_started']})
        progress.detail(str(error))
    except (step_repair.Paused, Failed) as error:
        out = Path(out)
        budget = read(out / 'budget.json')
        budget['status'] = error.status
        write_json(out / 'budget.json', budget)
        write_json(out / 'result.json', {'status': error.status, 'reason': error.reason, 'gui_actions': budget['gui_started']})
        progress.detail(error.reason)
    exploration_loop.finish(Path(run), Path(out))

def finalize_knowledge(root, run, out, *, max_http=6):
    """Use existing registration after GUI work is idle, with no GUI delivery."""
    from regrow.traversal import historical_inventory as _historical_inventory
    (root, run, out) = (Path(root).resolve(), Path(run).resolve(), Path(out).resolve())
    out.mkdir(parents=True, exist_ok=False)
    manifest = read(run / 'run_manifest.json')
    if manifest.get('platform') == 'desktop':
        from regrow.runtime.desktop_transport import DesktopRun
        transport = DesktopRun.__new__(DesktopRun)
        transport.configure(manifest)
    else:
        transport = RecoveryRun.__new__(RecoveryRun)
    transport.root = root
    transport.run = run
    transport.ledger = out / 'budget.json'
    transport.device = manifest['device']
    transport.package = manifest['app']
    transport.account = {'max_http': max_http, 'max_gui_commands': 0, 'http_started': 0, 'gui_started': 0, 'status': 'running'}
    transport.save()
    runner = step_repair.Runner(root, run, transport.call, transport.screenshot, lambda : transport.account['max_http'] - transport.account['http_started'])
    status = 'knowledge_complete'
    try:
        for _ in range(6):
            if step_repair.pending(run) or (run / 'execution_pending.json').exists():
                status = 'knowledge_pending'
                break
            (snapshot, records, state) = _record_load(run)
            q = _historical_inventory.request(root, snapshot, records, state)
            if not q:
                break
            if transport.account['http_started'] >= transport.account['max_http']:
                status = 'knowledge_pending'
                break
            runner.perform(q['stage'], q)
        else:
            status = 'knowledge_pending'
    except step_repair.Paused as error:
        status = error.status
    except BaseException:
        status = 'interrupted'
        raise
    finally:
        transport.account['status'] = status
        transport.save()
    result = {'status': status, 'http_started': transport.account['http_started'], 'gui_actions': 0}
    write_json(out / 'result.json', result)
    return result
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    run_step(SOURCE_ROOT, a.run, a.output)
