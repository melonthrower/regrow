from copy import deepcopy
from pathlib import Path
import jsonschema
from regrow.records.snapshots import read


def business_request(run, request):
    """A format retry answers the same business request, never another wrapper."""
    if request.get('format_original_call'):
        request = read(Path(run) / 'calls' / request['format_original_call'] / 'request.json')
    from regrow.recognition.named_references import internal_request
    return internal_request(request)

def submission(run, ref):
    """Resolve a corrected candidate without modifying the actual model artifacts."""
    from regrow.recognition import control_identity_review as _control_identity_review
    folder = Path(run) / 'calls' / ref
    q = read(folder / 'interpreted_request.json') if (folder / 'interpreted_request.json').exists() else business_request(run, read(folder / 'request.json'))
    reply = read(folder / 'interpreted_response.json') if (folder / 'interpreted_response.json').exists() else read(folder / 'response.json')
    if not q.get('display_regions') and (folder / 'response.json').exists():
        from regrow.recognition.named_references import display_regions
        hints = display_regions(read(folder / 'request.json'), read(folder / 'response.json'))
        if hints:
            q = {**q, 'display_regions': hints}
    if (folder / 'registration_candidate.json').exists():
        return read(folder / 'registration_request.json'), read(folder / 'registration_candidate.json')
    if (q.get('role') in ('step_correction', 'control_identity_comparison', 'action_target_review')
            and (folder / 'effective_request.json').exists() and (folder / 'effective_candidate.json').exists()):
        return read(folder / 'effective_request.json'), read(folder / 'effective_candidate.json')
    if q.get('role') == 'action_target_review':
        from regrow.recognition.action_target_review import accept
        return accept(q, reply, ref)
    if q.get('role') == 'control_identity_comparison':
        (original, candidate) = _control_identity_review.compared_candidate(q, reply)
        if candidate is None:
            raise ValueError('身份比较仍未确认，不能登记')
        return (original, candidate)
    if q.get('role') == 'step_correction':
        from regrow.records.task_assessments import planning, envelope
        if planning(q):
            envelope(reply, q['response_schema'])
        else:
            jsonschema.validate(reply, q['response_schema'])
        if q.get('correction_format') == 'original':
            from regrow.traversal.proposal_revision import merge
            if (folder / 'effective_request.json').exists() and (folder / 'effective_candidate.json').exists():
                return read(folder / 'effective_request.json'), read(folder / 'effective_candidate.json')
            return deepcopy(q['original_request']), merge(q, reply)
        normalized = folder / 'effective_candidate.json'
        if reply['resolution'] == 'edit_record' and normalized.exists():
            return (read(folder / 'effective_request.json'), read(normalized))
        if reply['resolution'] != 'revise' or reply['proposal'] is None:
            raise ValueError('not a revised candidate')
        effective = folder / 'effective_request.json'
        if effective.exists() and normalized.exists():
            return read(effective), read(normalized)
        from regrow.traversal.proposal_revision import merge
        return (read(effective) if effective.exists() else deepcopy(q['original_request']), merge(q, reply['proposal']))
    return (q, reply)
