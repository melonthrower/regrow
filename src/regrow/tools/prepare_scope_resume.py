"""Prepare a stopped run's explicit scope change; never execute GUI or model work.

Only explicitly selected Regions receive the existing inventory-review marker.
Task status, evidence and runtime observation are not rewritten by this tool.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from regrow.records import snapshots
from regrow.records.object_store import owned_tasks, region_work


def _atomic_bytes(path, content):
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(run, scope, regions=(), *, apply=False):
    """Return a dry-run plan by default; apply requires an already stopped run."""
    run = Path(run).resolve()
    scope = scope.strip()
    if not scope:
        raise ValueError('新运行范围不能为空')
    manifest_path = run / 'run_manifest.json'
    pointer_path = run / 'knowledge_current.json'
    manifest_before = manifest_path.read_bytes()
    pointer_before = pointer_path.read_bytes()
    manifest = json.loads(manifest_before)
    old_scope = manifest.get('exploration_scope', '')
    regions = list(dict.fromkeys(regions))
    plan = {'status': 'preview', 'run': str(run), 'old_scope': old_scope,
            'new_scope': scope, 'review_regions': regions,
            'tasks_are_not_reset': True, 'starts_runtime': False}
    if old_scope == scope:
        return {**plan, 'status': 'unchanged', 'review_regions': []}
    # A saved correction owns its original request/scope. Do not silently adopt
    # it into a different contract, or discard an unresolved execution pointer.
    pending = [name for name in ('pending_step.json', 'execution_pending.json')
               if (run / name).exists()]
    if pending:
        raise ValueError('先按原流程处理未结步骤，不能由范围变更覆盖：' + '、'.join(pending))
    _, records, state = snapshots.load(run)
    counts = {}
    for rid in regions:
        if rid not in records:
            raise ValueError('待复审区块不存在：' + rid)
        if region_work(records[rid]).get('out_of_scope_reason'):
            raise ValueError('区块已有独立范围排除，不能由本工具清除：' + rid)
        review = region_work(records[rid]).get('task_inventory', {}).get('review')
        if review and review.get('kind') != 'scope_change':
            raise ValueError('区块已有待办复核，不能覆盖：' + rid)
        counts[rid] = sum(t.get('status') in ('pending', 'blocked')
                          for t in owned_tasks(records[rid]).values())
    plan.update(unfinished_tasks=counts, retained_runtime_reason=state.get('reason'),
                scope_sha256=hashlib.sha256(scope.encode('utf-8')).hexdigest())
    if not apply:
        return plan
    from regrow.tools.debug_loop import live_run
    if live_run(run):
        raise ValueError('运行进程仍在活动；停止后才能应用范围变更')
    # Recheck the two files that define this plan before publishing any change.
    if manifest_path.read_bytes() != manifest_before or pointer_path.read_bytes() != pointer_before:
        raise ValueError('运行记录已变化，请停止运行后重新预览')
    change_id = 'scope-change-' + uuid.uuid4().hex
    change_dir = run / 'scope_changes' / change_id
    change_dir.mkdir(parents=True, exist_ok=False)
    (change_dir / 'run_manifest.before.json').write_bytes(manifest_before)
    (change_dir / 'knowledge_current.before.json').write_bytes(pointer_before)
    snapshots.write_json(change_dir / 'plan.json', {**plan, 'change': change_id})
    manifest = deepcopy(manifest)
    manifest['exploration_scope'] = scope
    manifest.setdefault('scope_history', []).append({
        'change': change_id, 'time': datetime.now(timezone.utc).isoformat(),
        'old_scope': old_scope, 'new_scope': scope, 'review_regions': regions})

    def mark_review(records, state, *_):
        for rid in regions:
            inventory = region_work(records[rid]).setdefault('task_inventory', {})
            inventory.setdefault('inventory', 'uncertain')
            inventory['review'] = {
                'kind': 'scope_change', 'change': change_id,
                'scope_sha256': plan['scope_sha256'],
                'reason': '本轮运行范围已显式变更；按新范围逐项复核原任务，保留原完成条件和真实阻塞。'}

    manifest_written = False
    try:
        # Existing snapshot transaction keeps the pointer unpublished until the
        # new manifest is written. Backups also permit recovery after process loss.
        with snapshots.transaction(run):
            pointer = snapshots.publish(run, change_id, mark_review)
            _atomic_bytes(manifest_path,
                          (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            manifest_written = True
    except BaseException:
        if manifest_written:
            _atomic_bytes(manifest_path, manifest_before)
        raise
    result = {**plan, 'status': 'applied', 'change': change_id,
              'backup': str(change_dir), 'snapshot': pointer['snapshot']}
    snapshots.write_json(change_dir / 'applied.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True, help='已停止的完整运行目录')
    parser.add_argument('--scope-file', type=Path, required=True, help='新的UTF-8运行范围文本')
    parser.add_argument('--review-region', action='append', default=[], help='明确受范围变化影响的区块ID，可重复')
    parser.add_argument('--apply', action='store_true', help='应用已预览的变更；默认只输出计划')
    args = parser.parse_args()
    result = prepare(args.run, args.scope_file.read_text(encoding='utf-8'),
                     args.review_region, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
