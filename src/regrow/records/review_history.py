from pathlib import Path
from regrow.records.object_store import region_work

def normalize(records, snapshot):
    """Old snapshots remain the source; rendered evidence is no longer copied."""
    for region in records.values():
        review = region_work(region).get('task_inventory', {}).get('review', {})
        if review.get('kind') != 'parameter_facts' or 'context' not in review:
            continue
        context = review.pop('context')
        attempts = {row.get('attempt') for row in context.get('过程来源', [])}
        attempts.update((row.get('记录') for key in ('相关动作', '最近连续动作', '此前动作与观察') for row in context.get(key, [])))
        review.update(snapshot=str(Path(snapshot).relative_to(Path(snapshot).parent.parent)), attempts=sorted(attempts - {None}))
        review.pop('frames', None)
