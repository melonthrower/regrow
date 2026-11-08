"""Stable numbered Region knowledge, updated without rewriting untouched paragraphs."""
from copy import deepcopy
import re
from regrow.records.diagnostics import reject

def normalize(region, records):
    """Read preserved old summaries once; never rewrite their original snapshot."""
    current = region.get('local_knowledge')
    if not current:
        return
    if all((re.fullmatch('k[0-9]+', key) and isinstance(value, str) for (key, value) in current.items())):
        for key in current:
            records.observe_id('knowledge', key)
        return
    parts = [current.get('summary', '')]
    parts += [row['description'] for row in current.get('conditions', []) if row.get('description')]
    region['local_knowledge'] = {records.allocate('knowledge'): text for text in parts if text.strip()}
    if current.get('parameters'):
        region['parameters'] = deepcopy(current['parameters'])

def validate(region, changes):
    current = region.get('local_knowledge', {})
    updated = [row['id'] for row in changes.get('update', [])]
    deleted = changes.get('delete', [])
    ids = updated + deleted
    if len(ids) != len(set(ids)):
        reject('region_knowledge_duplicate', region['name'], ids, '每个知识段落只修改或删除一次',
               field='区块知识修订', reason='同一知识段落在本次回复中被重复修改或删除。')
    if any((ref not in current for ref in ids)):
        reject('region_knowledge_reference', region['name'], [ref for ref in ids if ref not in current],
               list(current), field='区块知识引用', reason='部分被修改或删除的知识段落没有对应的已提供编号。')
    if any((not row['text'].strip() for row in changes.get('update', []))) or any((not text.strip() for text in changes.get('add', []))):
        reject('region_knowledge_empty', region['name'], changes, '非空的知识段落正文',
               field='区块知识正文', reason='新增或修改的知识段落正文为空。')

def apply(region, changes, records):
    validate(region, changes)
    result = deepcopy(region.get('local_knowledge', {}))
    for row in changes.get('update', []):
        result[row['id']] = row['text'].strip()
    for ref in changes.get('delete', []):
        del result[ref]
    for text in changes.get('add', []):
        result[records.allocate('knowledge')] = text.strip()
    region['local_knowledge'] = result
    return result

def text(region):
    return '\n'.join(region.get('local_knowledge', {}).values())


def related(records, region_ids):
    """Recall one hop from current object IDs or unique full names, never bind identity."""
    from regrow.records.object_store import owned_controls
    roots = set(region_ids) & records.keys()
    aliases = identity_aliases(records)
    owners = {rid: {rid} for rid in records}
    names = {}
    for rid, region in records.items():
        names.setdefault(region['name'], set()).add(rid)
        for cid, control in owned_controls(region).items():
            owners.setdefault(cid, set()).add(rid)
            names.setdefault(control['name'], set()).add(cid)
    unique = {name: next(iter(ids)) for name, ids in names.items() if name and len(ids) == 1}
    pattern = ('(?<![A-Za-z0-9_])(?:' + '|'.join(re.escape(name) for name in sorted(unique, key=len, reverse=True))
               + ')(?![A-Za-z0-9_])') if unique else None
    links = {}
    for rid, region in records.items():
        paragraph = text(region)
        refs = re.findall(r'(?<![A-Za-z0-9_])[rc]\d+(?![A-Za-z0-9_])', paragraph)
        if pattern:
            refs += [unique[match[0]] for match in re.finditer(pattern, paragraph)]
        links[rid] = {owner for ref in refs
                      for owner in owners.get(aliases.get(ref, {}).get('target', ref), ())} - {rid}
    selected = roots | {other for rid in roots for other in links[rid]}
    selected.update(rid for rid, targets in links.items() if targets & roots)
    return {rid: deepcopy(records[rid].get('local_knowledge', {})) for rid in records if rid in selected}


def context(records, region_ids):
    """Keep both sides' kIDs and actual routes; text never creates a graph edge."""
    from regrow.records.control_history_context import access_routes
    result = []
    aliases = identity_aliases(records)
    for rid, paragraphs in related(records, region_ids).items():
        row = {'ref': rid, '名称': records[rid]['name'], 'local_knowledge': paragraphs}
        routes = access_routes(records, rid, None)
        if routes:
            row['已验证的出现方式'] = routes
        if records[rid].get('merged_records'):
            row['已合并的历史身份'] = [{'id': old['id'], 'name': old['name']}
                                     for old in records[rid]['merged_records']]
        pending = []
        for old, alias in aliases.items():
            paragraphs_with_old_ref = [kid for kid, paragraph in paragraphs.items()
                                       if re.search(r'(?<![A-Za-z0-9_])' + re.escape(old) + r'(?![A-Za-z0-9_])', paragraph)]
            if paragraphs_with_old_ref:
                pending.append({'历史ID': old, '合并后ID': alias['target'], '当前名称': alias['name'],
                                '需核对引用的知识段落': paragraphs_with_old_ref})
        if pending:
            row['合并后的历史引用待核对'] = pending
        result.append(row)
    return result


def for_request(request, records):
    """Supply related editable history at the normal request production boundary."""
    if request.get('name_contract'):
        return request
    if request.get('role') not in {'observation', 'observation_update', 'task_proposal',
                                   'action_selection'}:
        return request
    from regrow.prompts.prompt_material import assign, body
    from regrow.recognition.control_references import _schemas
    source = request.get('source', {})
    roots = {source.get(key) for key in ('region', 'working_region', 'task_region')}
    roots.update(request.get('context_scope', {}).get('regions', []))
    discovery = request.get('discovery_context', {})
    roots.add(discovery.get('focus'))
    if not roots - {None}:
        roots.update(discovery.get('region_names', {}).values())
    rows = context(records, roots)
    if not any(row['local_knowledge'] for row in rows):
        return request
    ids = [row['ref'] for row in rows]
    for item in _schemas(request['response_schema'], 'regions'):
        props = item.get('properties', {})
        if set(props) <= {'ref', 'local_knowledge'} and 'ref' in props:
            writable = list(ids)
            props['ref']['enum'] = list(dict.fromkeys([*props['ref'].get('enum', []), *writable]))
    if discovery:
        discovery.setdefault('region_names', {}).update({rid: rid for rid in ids})
    if request.get('role') == 'observation_update':
        request.setdefault('region_names', {}).update({rid: rid for rid in ids})
    dynamic, _ = body(request)
    # These old single-owner slots now use the same selected paragraphs below.
    dynamic.pop('已有区块知识', None)
    dynamic.pop('区块已有知识', None)
    dynamic.pop('相关区块知识', None)
    for row in dynamic.get('已知区块', []):
        row.pop('local_knowledge', None)
    assign(request, {**dynamic, '可修订区块知识': rows},
           remove=('已有区块知识', '区块已有知识', '相关区块知识'))
    return request


def identity_aliases(records):
    from regrow.records.object_store import owned_controls
    from regrow.records.control_records import aliases as control_aliases
    result = {}
    for rid, region in records.items():
        for old in region.get('merged_records', []):
            result[old['id']] = {'target': rid, 'name': region['name'], 'old_name': old['name'], 'kind': 'region'}
        for cid, control in owned_controls(region).items():
            for old in control_aliases(control):
                result[old['id']] = {'target': cid, 'name': control['name'], 'old_name': old['name'], 'kind': 'control'}
    return result


def retarget(records):
    """A confirmed identity merge changes object references, not knowledge meaning."""
    aliases = identity_aliases(records)
    for region in records.values():
        for kid, paragraph in region.get('local_knowledge', {}).items():
            for old, alias in aliases.items():
                target = alias['target']
                old_label = re.escape(old + '/' + alias['old_name'])
                if alias['kind'] != 'region' or alias['old_name'] not in records[target].get('functions', {}):
                    paragraph = re.sub(old_label + r'(?=$|[\s，。；、：！？,.!?;:（）()\[\]「」“”])',
                                       lambda _: target + '/' + alias['name'], paragraph)
                paragraph = re.sub(r'(?<![A-Za-z0-9_])' + re.escape(old) + r'(?![A-Za-z0-9_/])', target, paragraph)
            region['local_knowledge'][kid] = paragraph
