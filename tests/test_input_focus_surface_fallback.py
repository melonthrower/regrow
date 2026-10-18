from regrow.runtime import input_target
from regrow.recognition import visual_backtrack

def test_missing_template_can_use_existing_surface_check_without_claiming_identity(monkeypatch):
    monkeypatch.setattr(input_target,'locate',lambda *args:None)
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *args:True)
    result=input_target.resolve({'source':{'region':'r','control':'c'}},'before','after')
    assert result['status']=='same_surface' and 'target' not in result

def test_changed_surface_still_blocks_unmatched_input(monkeypatch):
    monkeypatch.setattr(input_target,'locate',lambda *args:None)
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *args:False)
    assert input_target.resolve({'source':{}},'before','after')['status']=='unresolved'

def test_positive_identity_evidence_is_retained(monkeypatch):
    monkeypatch.setattr(input_target,'locate',lambda *args:{'control_box':[1,2,3,4]})
    result=input_target.resolve({'source':{'region':'r','control':'c'}},'before','after')
    assert result['status']=='same_target' and result['target']=={'region':'r','control':'c'}
