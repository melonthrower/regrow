"""Observed context candidates for owner-based summaries; never edit graph identities."""
from task_settlement import registration_kind


def related_regions(region, records):
    """Read direct connections and explicit parameter/task evidence dependencies.

    Arrival ancestry alone is not business containment: a navigation toolbar can
    appear after an unrelated click. Only parameter dependencies expand further.
    Luna judges the business purpose from the offered evidence.
    """
    records = records or {region['id']: region}
    owner = region['id']
    links = []
    for rid, candidate in records.items():
        for entry in candidate.get('reached_by', []):
            source = entry.get('source_region')
            action = records.get(source, {}).get('actions', {}).get(entry.get('attempt'), {})
            if source == rid or source not in records or action.get('delivery') != 'executed_receipt_zero':
                continue
            link = {'source': source, 'target': rid, 'control': entry.get('source_control'),
                    'attempt': entry.get('attempt'), 'operation': action.get('operation')}
            if link not in links:
                links.append(link)
    related = {owner}
    for link in links:
        if link['source'] == owner: related.add(link['target'])
        if link['target'] == owner: related.add(link['source'])
    # Explicit task visits and parameter provenance can cross several surfaces.
    frontier, expanded = [owner], set()
    while frontier:
        rid = frontier.pop()
        if rid in expanded: continue
        expanded.add(rid)
        for task in records[rid].get('tasks', {}).values():
            visits = {ref for ref in task.get('visited_regions', []) if ref in records}
            for fact in task.get('findings', {}).values():
                visits.update(source['region'] for source in fact.get('sources', [])
                              if source.get('region') in records)
            related.update(visits)
            if registration_kind(task) == 'parameter':
                visits.update(link['target'] for link in links
                              if link['source'] == rid and link['control'] == task.get('control'))
                related.update(visits)
                frontier.extend(visits - expanded)
    related = {rid for rid in related if not records[rid].get('out_of_scope_reason')}
    return [rid for rid in records if rid in related and rid != owner], [
        link for link in links if link['source'] in related and link['target'] in related]
