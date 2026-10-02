"""Project discovered Region functions from the exploration ledger."""

def region_function_inventory(ledger):
    """Project discovered functions, including unexecuted operations, from the ledger."""
    from .collection_graph import StepwiseCollectionGraph
    if isinstance(ledger, StepwiseCollectionGraph):
        return ledger.inventory()
    result = []
    for region in ledger.regions.values():
        operations = []
        for ref in region.canonical_operation_ids:
            canonical = ledger.canonical_operations.get(ref)
            if canonical is None:
                continue
            bindings = [ledger.operations[x] for x in canonical.operation_ids if x in ledger.operations]
            operations.append({
                "operation_ref": ref, "action": canonical.action, "target": canonical.target,
                "parameter_information": list(dict.fromkeys(x.parameter_summary for x in bindings if x.parameter_summary)),
                "observed_results": list(dict.fromkeys(x.result for x in bindings if x.result)),
            })
        if operations or region.memory or region.summary:
            result.append({
                "region_ref": region.region_id, "name": region.name,
                "memory": region.memory or region.summary, "operations": operations,
                "locations": list(dict.fromkeys(ledger.occurrences[x].state_id
                                                for x in region.occurrence_ids if x in ledger.occurrences)),
            })
    return result

__all__ = ["region_function_inventory"]
