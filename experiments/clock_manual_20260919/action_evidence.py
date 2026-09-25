"""Read delivered action types. Never infer an action from a label or screenshot."""
import json
from pathlib import Path


def resolve_operations(records, run):
    for rid, region in records.items():
        for aid, action in region.get('actions', {}).items():
            if action.get('operation'):
                continue
            path = Path(run) / 'action_attempts' / aid / 'dispatch.json'
            if not path.is_file():
                continue
            dispatch = json.loads(path.read_text())
            if dispatch.get('source_region') != rid or dispatch.get('source_control') != action.get('control'):
                continue
            delivered = dispatch.get('action', {})
            # Current proposal contract uses action; early delivery records used kind.
            action['operation'] = delivered.get('action') or delivered.get('kind')
