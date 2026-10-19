"""Numbered knowledge edits preserve unrelated facts and never reuse deleted IDs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from regrow.records import object_store as object_store
from regrow.records import region_knowledge as region_knowledge
from regrow.records.region_evidence import new_region as new_region

def test_patch_keeps_other_paragraphs_and_reserves_deleted_ids_on_reload(tmp_path):
    records = object_store.Records({'r0001': new_region('r0001', '条目编辑区')})
    region = records['r0001']
    region_knowledge.apply(region, {'add': ['保存条目。', '名称不能为空。']}, records)
    (first, second) = region['local_knowledge']
    region_knowledge.apply(region, {'update': [{'id': first, 'text': '保存后关闭编辑区。'}]}, records)
    assert region['local_knowledge'][second] == '名称不能为空。'
    region_knowledge.apply(region, {'delete': [second]}, records)

    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))
    object_store.save(records, tmp_path, write)
    restored = object_store.load(tmp_path)
    region_knowledge.apply(restored['r0001'], {'add': ['名称需要唯一。']}, restored)
    assert second not in restored['r0001']['local_knowledge']
    assert restored['r0001']['local_knowledge'][first] == '保存后关闭编辑区。'
    assert list(restored['r0001']['local_knowledge'].values())[-1] == '名称需要唯一。'

def test_unknown_or_conflicting_edits_do_not_change_knowledge_or_numbering():
    records = object_store.Records({'r0001': new_region('r0001', '条目编辑区')})
    region_knowledge.apply(records['r0001'], {'add': ['保存条目。']}, records)
    baseline = deepcopy(records.packed())
    for changes in ({'update': [{'id': 'k9999', 'text': '未知引用'}]}, {'update': [{'id': 'k0001', 'text': '改写'}], 'delete': ['k0001']}):
        with pytest.raises(ValueError):
            region_knowledge.apply(records['r0001'], changes, records)
        assert records.packed() == baseline

def test_import_keeps_conditions_and_structured_parameters_without_role_fields():
    original = new_region('r0001', '编辑区')
    original.update(region_role='functional', role_evidence='有编辑功能。', scope_history=[{'previous_reason': ''}], local_knowledge={'summary': '编辑并保存条目。', 'conditions': [{'description': '名称不能为空。', 'tasks': ['名称限制']}], 'parameters': {'名称': {'domain': {'type': 'text'}, 'conditions': ['不能留空']}}})
    before = deepcopy(original)
    records = object_store.Records({'r0001': original})
    assert original == before
    assert list(records['r0001']['local_knowledge'].values()) == ['编辑并保存条目。', '名称不能为空。']
    assert records['r0001']['constraints']['名称']['conditions'] == ['不能留空']
    assert not {'region_role', 'role_evidence', 'scope_history'} & records['r0001'].keys()

def test_paragraph_projection_keeps_review_status_and_empty_review_can_be_current():
    from regrow.records import function_scope as function_scope
    from regrow.prompts import prompt_material as prompt_material
    from regrow.traversal import region_functions as region_functions
    from regrow.records.task_knowledge import summary_view as summary_view
    records = object_store.Records({'r0001': new_region('r0001', '编辑区')})
    region = records['r0001']
    region_knowledge.apply(region, {'add': ['保存条目。']}, records)
    projected = prompt_material.map_knowledge(summary_view(function_scope.disclose(records, 'r0001')))
    assert projected['self']['status'] == 'needs_review'
    assert list(projected['knowledge'].values()) == ['保存条目。']
    region_knowledge.apply(region, {'delete': list(region['local_knowledge'])}, records)
    object_store.region_work(region)['function_inventory'] = {'source_call': '2', 'evidence_digest': region_functions.signature(region, records)}
    assert function_scope.card(region, records)['status'] == 'summarized'
