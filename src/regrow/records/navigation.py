from regrow.records.object_store import owned_actions
'Read recorded navigation meaning without deciding the next action.'

def contextual_return(action):
    """Historical endpoint is not a promise about the current navigation stack."""
    return action.get('operation') == 'back' or bool(action.get('return_context'))

def navigation_description(action):
    description = action.get('result', {}).get('description', '')
    if contextual_return(action):
        context = action.get('return_context', {})
        return ('返回尝试；实际落点：' + '、'.join(context.get('targets', []))
                + '；进入尝试：' + str(context.get('entry_attempt') or '未绑定')
                + ('；历史观察：' + description if description else ''))
    return description


def bind_return(records, source, attempt):
    """Attach observed return targets to this visit's actual incoming attempt."""
    from regrow.records.action_evidence import has_observed_result
    from regrow.records.object_store import incoming
    action = owned_actions(records[source])[attempt]
    if action.get('operation') != 'back' or not has_observed_result(action) or action['result']['exception'] != 'none':
        return
    targets = [rid for rid in action.get('observed_destinations', []) if rid != source]
    entries = []
    for edge in incoming(records[source], records):
        aid = edge['attempt']
        previous = owned_actions(records[edge['source_region']]).get(aid, {})
        if aid < attempt and not contextual_return(previous) and has_observed_result(previous) and previous['result']['exception'] == 'none':
            entries.append(edge)
    entry = max(entries, key=lambda row: row['attempt']) if entries else {}
    if not targets:
        return
    action['return_context'] = {'entry_attempt': entry.get('attempt'),
        'entry_region': entry.get('source_region'), 'entry_control': entry.get('source_control'),
        'targets': targets, 'source_region': source, 'source_control': action.get('control'),
        'evidence': dict(action['evidence'])}

def known_entries(region, control, operation):
    if operation not in ('tap', 'click'):
        return []
    hits = []
    for (aid, action) in owned_actions(region).items():
        if action.get('control') != control or action.get('operation') not in ('tap', 'click') or action.get('delivery') != 'executed_receipt_zero' or (action.get('text_delivered') is False) or (action.get('result', {}).get('exception') != 'none') or contextual_return(action):
            continue
        targets = list(dict.fromkeys(action.get('observed_destinations', action.get('interactive_regions', []))))
        if len(targets) != 1 or targets[0] == region['id']:
            continue
        hits.append({'attempt': aid, 'destination_region': targets[0], 'description': action['result'].get('description', ''), 'conditions': action.get('conditions', [])})
    return hits
