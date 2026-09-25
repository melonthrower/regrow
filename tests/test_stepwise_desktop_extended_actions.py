import pytest
from tests.test_stepwise_desktop import action, ROOT, mod, module_path

@pytest.mark.parametrize('kind,fields,code',[
 ('key_press',{'text':'F11'},"press('f11')"),
 ('hotkey',{'text':'CTRL+SHIFT+P'},"hotkey('ctrl', 'shift', 'p')"),
 ('hover',{},'moveTo(12,24)'),
 ('right_click',{},"click(12,24,button='right')"),
 ('drag',{'end_x':40,'end_y':60},'dragTo(40,60'),
])
def test_desktop_extended_delivery_and_validation(kind,fields,code):
    m=mod('action_commands');p=action(kind,**fields)
    m.validate(p,platform='desktop')
    assert code in m.commands(p,'desktop')[0]
    with pytest.raises(ValueError):m.commands(p,'android')


def test_hotkey_rejects_code_not_keys():
    with pytest.raises(ValueError):mod('action_commands').commands(action('hotkey',text="ctrl+__import__('os')"),'desktop')

@pytest.mark.parametrize('kind',['key_press','hotkey'])
def test_keyboard_dispatch_requires_same_observed_foreground(kind,monkeypatch):
    m=mod('run_task_step');import visual_backtrack
    monkeypatch.setattr(visual_backtrack,'same_surface',lambda *a:True)
    assert m.system_action_changed(kind,'before','after','terminal','other-app')

@pytest.mark.parametrize('kind',['key_press','hotkey'])
def test_keyboard_checks_changed_focus_surface_inside_same_window(kind,monkeypatch):
    m=mod('run_task_step')
    monkeypatch.setattr(m.visual_backtrack,'same_surface',lambda *a:False)
    assert m.system_action_changed(kind,'before','after','terminal','terminal')
