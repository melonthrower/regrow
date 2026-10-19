"""Read-only source-action recall and historical identity text."""
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_controls

def recall(records, binding, operation, attempt):
    owner = records.get(binding.get('region_ref'), {})
    control = binding.get('control_ref')
    confirmed = control in owned_controls(owner) and binding.get('association', {}).get('status') != 'unconfirmed'
    rows = []
    if confirmed:
        for (ref, action) in sorted(owned_actions(owner).items()):
            if ref >= attempt or action.get('control') != control or action.get('operation') != operation:
                continue
            if action.get('delivery') != 'executed_receipt_zero':
                continue
            targets = [r for r in action.get('interactive_regions', []) if r in records and r != binding['region_ref']]
            changed = {r['region'] for r in action.get('region_changes', []) if r.get('state') == 'changed_interactive'}
            if not targets:
                continue
            targets.sort(key=lambda r: r not in changed)
            rows.append({'attempt': ref, 'description': action.get('result', {}).get('description', ''), 'destinations': targets, 'changed': [r for r in targets if r in changed], 'result_call': action.get('evidence', {}).get('result_call'), 'after_observation': action.get('evidence', {}).get('after_observation')})
    rows = rows[-3:]
    destinations = list(dict.fromkeys((r for a in reversed(rows) for r in a['destinations'])))
    return {'confirmed': confirmed, 'actions': rows, 'destinations': destinations}

def describe(recalled, labels):
    return {'来源关联': '已确认同一控件与动作' if recalled['confirmed'] else '来源控件未确认；不按同入口推断落点', '历史结果': [{'动作': a['attempt'], '观察结果': a['description'], '当时可交互区块': [labels[r] for r in a['destinations'] if r in labels]} for a in recalled['actions']], '边界': '历史落点只是优先候选；不同入口也可到达同一区块，候选缺失不等于新区块。'}
