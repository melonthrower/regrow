import pytest
from tests.test_recovery_discovery import mod


def test_empty_current_task_diagnostic_names_actual_owner_and_identity_repair():
    task={'control':'new','status':'pending','attempts':[],'task_type':'single_action'}
    region={'id':'r','name':'Player','controls':{'new':{'name':'Current play'}},'tasks':{'Observe feedback':task}}
    with pytest.raises(ValueError) as error:
        mod('task_result_review').apply(region,{},'Observe feedback',{'name':'Observe feedback','status':'done','evidence':'Old playback responded'},'review')
    message=str(error.value)
    assert 'Observe feedback' in message and 'Current play' in message
    assert 'merge_into' in message and '其他控件' in message
    assert task['status']=='pending' and task['attempts']==[]
