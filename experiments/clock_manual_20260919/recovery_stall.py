"""Compare executed recovery attempts, independently of whole-screen similarity."""


def repeated_attempt(episode, proposal):
    """A newly exposed control is not a repeat just because most pixels match."""
    def signature(value):
        tool = value.get('framework_tool')
        if tool:
            return ('tool', tool)
        action = value.get('action') or {}
        if not action.get('action'):
            return None
        return tuple(action.get(key) for key in ('action', 'x', 'y', 'end_x', 'end_y', 'text'))

    candidate = signature(proposal)
    return candidate is not None and any(
        row.get('delivery') == 'executed_receipt_zero' and signature(row) == candidate
        for row in episode.get('actions', [])[-8:])
