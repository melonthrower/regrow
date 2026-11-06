"""Reuse a true Control identity across behavior variants."""
from regrow.records.object_store import owned_controls

def extend_link(records, old_region, old_control, new_region, new_control, evidence, call):
    """Reuse one identity when a behavior split explicitly retains this control."""
    from regrow.records import control_records
    old = owned_controls(records[old_region])[old_control]
    owned_controls(records[new_region]).setdefault(old_control, old)
    if new_control != old_control:
        control_records.merge(records, {}, new_region, [new_control], old_control)
