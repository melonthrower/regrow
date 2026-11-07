"""Object knowledge edits shared by observations, task reviews and no-action answers."""
from regrow.records.object_store import control_record
from regrow.records import control_knowledge, region_knowledge
from regrow.records.diagnostics import reject


def control_only(row):
    return bool(row.get('ref') and 'knowledge' in row and
                set(row) <= {'ref', 'identity', 'name', '_matched_id', 'knowledge'})


def region_only(row):
    return bool(row.get('ref') and 'local_knowledge' in row and
                set(row) <= {'ref', 'identity', 'name', '_matched_id', 'local_knowledge'})


def region_schema():
    string = {'type': 'string', 'minLength': 1}
    return {'type': 'object', 'properties': {
        'add': {'type': 'array', 'items': string},
        'update': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'id': string, 'text': string}, 'required': ['id', 'text'], 'additionalProperties': False}},
        'delete': {'type': 'array', 'items': string}}, 'additionalProperties': False}


def fields(records, region_ids):
    """Only edits to supplied objects; no new observation or identity claim."""
    from regrow.records.object_store import owned_controls
    ids = list(dict.fromkeys(cid for rid in region_ids if rid in records for cid in owned_controls(records[rid])))
    return {
        'controls': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'ref': {'type': 'string', 'enum': ids}, 'knowledge': control_knowledge.schema()},
            'required': ['ref', 'knowledge'], 'additionalProperties': False}},
        'regions': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'ref': {'type': 'string', 'enum': list(region_knowledge.related(records, region_ids))}, 'local_knowledge': region_schema()},
            'required': ['ref', 'local_knowledge'], 'additionalProperties': False}}}


def apply(records, reply, source):
    """Called inside the same transaction, before task assessment."""
    for row in reply.get('controls', []):
        if not control_only(row):
            reject('knowledge_edit_fields', row.get('ref') or row.get('name') or '本次控件', row,
                   '已有控件引用及需要修订的 knowledge', field='控件知识修订',
                   reason='本次知识修订混入了当前外观或其他非知识字段。')
        record = control_record(records, row['ref'])
        if record is None:
            reject('knowledge_control_reference', row['ref'], row['ref'], '已提供的已有控件引用',
                   field='控件知识修订', reason='知识修订引用没有对应的已登记控件。')
        control_knowledge.update(record, row['knowledge'], source)
    for row in reply.get('regions', []):
        if not region_only(row) or row['ref'] not in records:
            reject('knowledge_region_reference', row.get('ref') or row.get('name') or '本次区块', row,
                   '已提供区块的引用及 local_knowledge', field='区块知识修订',
                   reason='该条目没有对应的已提供区块，或混入了区块知识之外的字段。')
        region_knowledge.validate(records[row['ref']], row['local_knowledge'])
        region_knowledge.apply(records[row['ref']], row['local_knowledge'], records)


def observed_refs(reply, refs):
    return [rid for row, rid in zip(reply.get('regions', []), refs) if not region_only(row)]
