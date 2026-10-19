from regrow.records.control_history_context import purpose_text

def test_initial_discovery_knowledge_is_read_as_a_guess():
    c={'knowledge':'打开搜索','observations':[{'knowledge':'打开搜索','evidence':{'observation':'discovery:0001','source_field':'/controls/0'}}]}
    assert purpose_text(c)=='推测用途：打开搜索'
    c['observations'].append({'knowledge':'打开搜索','evidence':{'task_ref':'r1/task','basis':'explored'}})
    assert purpose_text(c)=='已知功能：打开搜索'

def test_missing_source_is_not_called_confirmed_or_discovery():
    assert purpose_text({'knowledge':'旧描述'})=='历史用途（缺少确认依据）：旧描述'
