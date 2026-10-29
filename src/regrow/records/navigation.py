from regrow.records.object_store import owned_actions
'Read recorded navigation meaning without deciding the next action.'

def contextual_return(action):
    """Historical endpoint is not a promise about the current navigation stack."""
    return action.get('operation') == 'back' or action.get('result', {}).get('returns_to_previous') is True

def navigation_description(action):
    description = action.get('result', {}).get('description', '')
    if contextual_return(action):
        return '返回或关闭浮层后恢复进入前的界面，目标取决于进入路径；历史观察：' + description
    return description

def known_entries(region, control, operation):
    if operation not in ('tap', 'click'):
        return []
    hits = []
    for (aid, action) in owned_actions(region).items():
        if action.get('control') != control or action.get('operation') not in ('tap', 'click') or action.get('delivery') != 'executed_receipt_zero' or (action.get('text_delivered') is False) or (action.get('result', {}).get('exception') != 'none') or (action.get('result', {}).get('returns_to_previous') is True):
            continue
        targets = list(dict.fromkeys(action.get('interactive_regions', [])))
        if len(targets) != 1 or targets[0] == region['id']:
            continue
        hits.append({'attempt': aid, 'destination_region': targets[0], 'description': action['result'].get('description', ''), 'conditions': action.get('conditions', [])})
    return hits
