"""An existing control under another owner needs a concrete diagnostic, not an empty name list."""
from copy import deepcopy
from regrow.records import registration_diagnostics as registration_diagnostics

def test_update_reports_supplied_old_owner_without_rebinding_or_mutating_records():
    records = {'toolbar': {'name': 'Toolbar', 'controls': {}}, 'content': {'name': 'Content', 'controls': {'c1': {'name': 'Add'}}}}
    before = deepcopy(records)
    q = {'region_names': {'Toolbar': 'toolbar', 'Content': 'content'}}
    reply = {'regions': [{'name': 'Toolbar', 'previous_name': 'Toolbar', 'parent_index': None}], 'controls': [{'name': 'Add', 'previous_name': 'Add', 'region_index': 0}]}
    report = registration_diagnostics.collect('update', q, reply, records)
    issue = next((e for e in report['errors'] if e['code'] == 'unknown_candidate_control'))
    assert issue['actual']['registered_region'] == 'content' and issue['actual']['control'] == 'c1'
    assert issue['expected']['proposed_region'] == 'toolbar' and 'record_edit' in issue['repair']
    assert records == before
