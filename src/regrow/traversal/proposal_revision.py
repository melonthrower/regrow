"""Merge an update correction into its retained semantic proposal before acceptance."""
from copy import deepcopy

def prepare(job, original, schema):
    from regrow.traversal.object_registration import semantic_revision
    if job['stage'] != 'update' or job.get('control_identity_pair') or job.get('control_identity_candidates'):
        return None
    base = job.get('candidate')
    if not isinstance(base, dict) or not base:
        return None
    _, base = semantic_revision(job['request'], base)
    allowed = schema.get('properties', {})
    if not allowed or set(base) - set(allowed):
        return None
    schema['required'] = []
    schema['minProperties'] = 1
    return deepcopy(base)

def merge(request, proposal):
    if 'proposal_base' not in request:
        return proposal
    if not isinstance(proposal, dict):
        raise ValueError('revise需要提供本次修订的字段')
    return {**deepcopy(request['proposal_base']), **deepcopy(proposal)}
