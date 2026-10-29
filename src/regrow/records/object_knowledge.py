"""Object knowledge edits shared by observations, task reviews and no-action answers."""
from regrow.records.object_store import control_record
from regrow.records import control_knowledge, region_knowledge


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
            'ref': {'type': 'string', 'enum': list(region_ids)}, 'local_knowledge': region_schema()},
            'required': ['ref', 'local_knowledge'], 'additionalProperties': False}}}


def apply(records, reply, source):
    """Called inside the same transaction, before task assessment."""
    for row in reply.get('controls', []):
        if not control_only(row):
            raise ValueError('知识修订只引用已提供控件并更新knowledge，不报告前台外观')
        record = control_record(records, row['ref'])
        if record is None:
            raise ValueError('知识修订引用的控件不存在：' + row['ref'])
        control_knowledge.update(record, row['knowledge'], source)
    for row in reply.get('regions', []):
        if not region_only(row) or row['ref'] not in records:
            raise ValueError('区块知识修订须引用已提供区块及local_knowledge')
        region_knowledge.validate(records[row['ref']], row['local_knowledge'])
        region_knowledge.apply(records[row['ref']], row['local_knowledge'], records)
    if reply.get('function_updates'):
        from regrow.records.function_updates import apply as apply_functions
        apply_functions(records, reply['function_updates'], source)


def observed_refs(reply, refs):
    return [rid for row, rid in zip(reply.get('regions', []), refs) if not region_only(row)]
