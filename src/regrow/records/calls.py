from copy import deepcopy
from pathlib import Path
import jsonschema
from regrow.records.snapshots import read

def submission(run, ref):
    """Resolve a corrected candidate without modifying the actual model artifacts."""
    from regrow.recognition import control_identity_review as _control_identity_review
    folder = Path(run) / 'calls' / ref
    q = read(folder / 'request.json')
    reply = read(folder / 'response.json')
    if (folder / 'registration_candidate.json').exists():
        return read(folder / 'registration_request.json'), read(folder / 'registration_candidate.json')
    if q.get('role') == 'control_identity_comparison':
        (original, candidate) = _control_identity_review.compared_candidate(q, reply)
        if candidate is None:
            raise ValueError('身份比较仍未确认，不能登记')
        return (original, candidate)
    if q.get('role') == 'step_correction':
        jsonschema.validate(reply, q['response_schema'])
        normalized = folder / 'effective_candidate.json'
        if reply['resolution'] == 'edit_record' and normalized.exists():
            return (read(folder / 'effective_request.json'), read(normalized))
        if reply['resolution'] != 'revise' or reply['proposal'] is None:
            raise ValueError('not a revised candidate')
        effective = folder / 'effective_request.json'
        return (read(effective) if effective.exists() else deepcopy(q['original_request']), deepcopy(reply['proposal']))
    return (q, reply)
