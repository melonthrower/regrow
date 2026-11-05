from regrow.records.object_store import region_work
'Carry durable task-inventory gaps into local control discovery.'

def supplement(root, region, dynamic, parts):
    gap = region_work(region).get('registration_gaps', {}).get('discovery', {})
    if not gap.get('pending'):
        return
    dynamic['本区块待补登记'] = {'尚未接受的观察对象': [row.get('name') or row.get('item') for row in gap['pending']]}
    from regrow.prompts.compose import supplement
    parts.append(supplement(root, 'inventory_gap'))
