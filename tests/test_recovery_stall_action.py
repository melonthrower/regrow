"""Visual similarity alone must not suppress a newly exposed recovery control."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def test_new_close_after_hover_is_not_a_repeated_recovery_action():
    spec = importlib.util.spec_from_file_location('recovery_stall', ROOT/'recovery_stall.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    episode = {'actions': [
        {'delivery':'executed_receipt_zero', 'action':{'action':'wait'}},
        {'delivery':'executed_receipt_zero', 'action':{'action':'wait'}},
        {'delivery':'executed_receipt_zero', 'action':{'action':'hover','x':908,'y':43}}]}
    click = {'decision':'act','action':{'action':'click','x':900,'y':55},'framework_tool':None}
    assert not module.repeated_attempt(episode, click)
    assert module.repeated_attempt(episode, {'action':{'action':'wait','reason':'a new explanation'}})
    assert module.repeated_attempt(episode, {'action':{'action':'hover','x':908,'y':43,'target':'renamed'}})
    episode['actions'].append({'delivery':'unconfirmed','action':click['action']})
    assert not module.repeated_attempt(episode, click)  # Separate uncertain-delivery guard owns this.
    episode['actions'][-1]['delivery'] = 'executed_receipt_zero'
    assert module.repeated_attempt(episode, click)
