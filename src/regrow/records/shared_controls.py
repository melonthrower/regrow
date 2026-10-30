"""Reuse global control identities; read former behavior groups for old records."""
from regrow.records.object_store import owned_actions
from regrow.records.object_store import owned_tasks
from regrow.records.object_store import owned_controls
from copy import deepcopy
from regrow.records import shared_tasks as shared_tasks

def refresh(records):
    """Refresh canonical behavior from actual member actions, never copy attempts."""
    for owner in records.values():
        for group in owner.get('shared_controls', {}).values():
            if group.get('status') == 'separated':
                continue
            results = []
            contexts = {}
            broken = False
            for member in group['members']:
                (rid, cid) = (member['region'], member['control'])
                region = records.get(rid, {})
                c = owned_controls(region).get(cid)
                if not c:
                    broken = True
                    continue
                for (aid, a) in owned_actions(region).items():
                    if a.get('control') != cid or a.get('delivery') != 'executed_receipt_zero':
                        continue
                    result = a.get('result', {})
                    if not result.get('description'):
                        continue
                    targets = list(a.get('interactive_regions', []))
                    row = {'source': {'region': rid, 'control': cid, 'attempt': aid}, 'operation': a.get('operation'), 'description': result['description'], 'evidence': result.get('evidence', ''), 'exception': result.get('exception'), 'destination_regions': targets, 'conditions': list(a.get('conditions', []))}
                    results.append(row)
                    if result.get('exception') != 'none':
                        broken = True
                    if targets and a.get('operation') in ('tap', 'click') and (not result.get('returns_to_previous')):
                        before = set(a.get('evidence', {}).get('before_regions', []))
                        direct = set(targets) - before - {rid}
                        if direct:
                            from regrow.records.control_context import conditions
                            (destinations, members) = contexts.setdefault(conditions(row), (set(), set()))
                            destinations.add(tuple(sorted(direct)))
                            members.add((rid, cid))
            group['results'] = results
            from regrow.records.shared_control_review import signature
            reviewed = group.get('reviewed_signature') == signature(group)
            group['status'] = 'needs_review' if broken or (not results and (not group.get('proposal_evidence'))) or (any((len(members) > 1 and len(destinations) > 1 for (destinations, members) in contexts.values())) and (not reviewed)) else 'confirmed'
    shared_tasks.synchronize_tasks(records)

def view(records, rid, cid):
    groups = [group for owner in records.values()
              for group in owner.get('shared_controls', {}).values()
              if group.get('status') != 'separated'
              and {'region': rid, 'control': cid} in group.get('members', [])]
    return deepcopy(groups[0]) if len(groups) == 1 else None


def disclose(records, rid, cid):
    group = view(records, rid, cid)
    if not group:
        return []
    return [{'共享关系': group['name'], '关联区块': [records.get(m['region'], {}).get('name', m['region']) for m in group['members']], '共享范围': '行为知识；当前状态、位置和执行记录仍属于各自控件', '已观察结果': [{'来源区块': records.get(row['source']['region'], {}).get('name', ''), '结果': row['description'], '依据': row['evidence'], '适用条件': row.get('conditions', []), '目的区块': [records.get(r, {}).get('name', r) for r in row['destination_regions']]} for row in group['results']], '用途': '共享结果存在冲突或成员缺失，需重新核对，不能据此跳过探索' if group['status'] == 'needs_review' else '关联入口的已有行为证据；结合当前对象和状态判断适用性，不代表本地已执行'}]

def render(records, rid):
    lines = []
    for (cid, c) in owned_controls(records[rid]).items():
        group = view(records, rid, cid)
        if not group:
            continue
        lines.append('共享控件「' + c['name'] + '」：' + ('关系需重新核对' if group['status'] == 'needs_review' else '关联入口行为已确认'))
        for row in group['results']:
            source = records.get(row['source']['region'], {}).get('name', row['source']['region'])
            lines.append('  ' + source + '中实际观察：' + row['description'] + '；适用条件：' + str(row.get('conditions', [])))
        lines.append('  不代表本区块已执行；本地状态与任务仍分别登记。')
    return lines

def extend_link(records, old_region, old_control, new_region, new_control, evidence, call):
    """Reuse one identity when a behavior split explicitly retains this control."""
    from regrow.records import control_records
    old = owned_controls(records[old_region])[old_control]
    owned_controls(records[new_region]).setdefault(old_control, old)
    if new_control != old_control:
        control_records.merge(records, {}, new_region, [new_control], old_control)

def propose_instances(records, rid, rows, call, state=None):
    """Explicitly reuse one global control record in another Region."""
    from regrow.records import control_records
    from regrow.records.object_store import control_record
    renamed = {}
    for row in rows:
        owners = [row['source_region']] if row['source_region'] in records else []
        if len(owners) != 1:
            raise ValueError('复用来源区块必须唯一')
        source = owners[0]
        ids = [row['source_control']] if row['source_control'] in owned_controls(records[source]) else []
        local = [row['control']] if row['control'] in owned_controls(records[rid]) else []
        if len(ids) != 1 or len(local) != 1 or not row['reason'].strip():
            raise ValueError('复用需要明确的本区块控件和已有控件')
        target, previous = ids[0], local[0]
        owned_controls(records[rid]).setdefault(target, control_record(records, target))
        if previous != target:
            control_records.merge(records, state if state is not None else {}, rid, [previous], target)
        renamed[row['control']] = target
    return renamed
