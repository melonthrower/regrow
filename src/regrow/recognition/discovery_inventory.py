from regrow.records.object_store import region_work
'Carry durable task-inventory gaps into local control discovery.'

def supplement(root, region, dynamic, parts):
    inventory = region_work(region).get('task_inventory', {})
    if inventory.get('inventory') not in ('partial', 'uncertain') or not inventory.get('evidence'):
        return
    dynamic['本区块待补登记'] = {'清点时发现的具体缺口': inventory['evidence']}
    from regrow.prompts.compose import supplement
    parts.append(supplement(root, 'inventory_gap'))
