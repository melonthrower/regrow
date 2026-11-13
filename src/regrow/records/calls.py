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
    if q.get('role') in ('action_target_review', 'control_identity_comparison'):
        raise ValueError('历史身份核对尚无已接收结果；请查看该次冻结源码及原始记录，不在当前流程重发退役调用。')
    if q.get('role') == 'step_correction':
        from regrow.records.task_assessments import planning, envelope
        if planning(q):
            envelope(reply, q['response_schema'])
        else:
            from regrow.runtime.update_reply import main_pair
            spec, main = main_pair(q['response_schema'], reply)
            jsonschema.validate(main, spec)
        if q.get('correction_format') == 'original':
            from regrow.traversal.proposal_revision import continuation_source, merge
            if (folder / 'effective_request.json').exists() and (folder / 'effective_candidate.json').exists():
                return read(folder / 'effective_request.json'), read(folder / 'effective_candidate.json')
            return continuation_source(q['original_request'], q, reply), merge(q, reply)
        normalized = folder / 'effective_candidate.json'
        if reply['resolution'] == 'edit_record' and normalized.exists():
            return (read(folder / 'effective_request.json'), read(normalized))
        if reply['resolution'] != 'revise' or reply['proposal'] is None:
            raise ValueError('not a revised candidate')
        effective = folder / 'effective_request.json'
        if effective.exists() and normalized.exists():
            return read(effective), read(normalized)
        from regrow.traversal.proposal_revision import continuation_source, merge
        original = read(effective) if effective.exists() else q['original_request']
        return continuation_source(original, q, reply['proposal']), merge(q, reply['proposal'])
    return (q, reply)


def action_submission(run, ref, field=None):
    """Read either a selection reply or the Action subtree of a real update."""
    if field != 'next_action':
        return submission(run, ref)
    request = read(Path(run) / 'calls' / ref / 'next_action_context.json')
    reply = read(Path(run) / 'calls' / ref / 'next_action_candidate.json')
    return request, reply
