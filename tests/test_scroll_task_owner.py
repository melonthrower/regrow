"""Reject proposals that cannot match the normal Region-owned scroll receipt."""
import pytest
import region_tasks
from tests.test_stepwise_region_tasks import fixture, row, proposal


@pytest.mark.parametrize('inventory', ['complete', 'partial'])
def test_control_owned_scroll_is_rejected_before_registration(inventory):
    _, records, _ = fixture()
    owner = records['menu']
    operation = {**row(), 'name': '查看列表后续', 'action': 'scroll',
                 'task_type': 'scroll'}
    with pytest.raises(ValueError, match='滚动任务.*control'):
        region_tasks.apply_plan(owner, proposal([operation], inventory), 'new-call')
    assert not owner.get('tasks')
