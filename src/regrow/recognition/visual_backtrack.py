from regrow.records.snapshots import publish as _record_publish
"""Read-only handoff for archived navigation delivery with an unknown result."""
import json
import uuid
from regrow.records.snapshots import read



def handoff(transport, frame, event, reason):
    run = transport.run
    edge = event['edge']
    note = {'reason': reason, **event, 'frame': str(frame)}

    def change(records, state, *args):
        state.update(next_action_mode='discover', phase='awaiting_discovery', interactive_regions=[], observation=None, pending_frame=str(frame), navigation_handoff=note, correction_context='自动回溯交接：' + json.dumps(note, ensure_ascii=False) + '。先确认当前落点，不重放未确认动作；寻找其他入口时先发现登记。')
        state.setdefault('navigation_failed_edges', [])
        if edge['attempt'] not in state['navigation_failed_edges']:
            state['navigation_failed_edges'].append(edge['attempt'])
        state.pop('visual_navigation', None)
    _record_publish(run, 'navigation-handoff-' + uuid.uuid4().hex[:12], change)
    (run / 'visual_navigation_pending.json').unlink(missing_ok=True)
    return {'status': 'ready_next_round', 'navigation': 'luna_handoff', 'reason': reason, 'gui_actions': int(event.get('status') in ('executed', 'dispatching', 'unconfirmed'))}

def resume_pending(transport, frame):
    path = transport.run / 'visual_navigation_pending.json'
    if not path.exists():
        return None
    return handoff(transport, frame, read(path), '上轮回溯已开始投递但落点未提交，先观察现场，禁止自动重放')
