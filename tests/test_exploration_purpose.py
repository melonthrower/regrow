"""Offline checks for purpose records and task material; no model or GUI calls."""
from pathlib import Path
import unittest

from regrow.records.object_store import Records, owned_controls, owned_tasks, owned_actions
from regrow.records import object_knowledge, control_knowledge
from regrow.records.control_history_context import purpose_text
from regrow.records.task_inventory_context import project


ROOT = Path(__file__).resolve().parents[1] / 'src'


def purpose_fixture():
    """Illustrative facts, deliberately without physical execution evidence."""
    records = Records({'r0001': {
        'id': 'r0001', 'name': '示例应用', 'description': '本离线例子中的窗口与功能入口。',
        'controls': {
            'c0001': {'name': '最大化窗口', 'description': '明确的窗口操作。',
                      'knowledge': [], 'needs_exploration': False, 'may_open_content': False},
            'c0002': {'name': '设置入口', 'description': '打开尚未观察的设置内容。',
                      'knowledge': [], 'needs_exploration': False, 'may_open_content': True},
        }, 'tasks': {},
    }})
    object_knowledge.apply(records, {'controls': [
        {'ref': 'c0001', 'knowledge': [{'description': '将当前窗口最大化。'}]},
        {'ref': 'c0002', 'knowledge': [{'description': '打开设置；面板内提供哪些功能尚不清楚。'}]},
    ]}, {'source_call': 'offline_observation', 'basis': 'observation_only'})
    state = {'working_region': 'r0001', 'interactive_regions': ['r0001'],
             'observation': {'id': 'offline', 'image': 'OFFLINE_NO_IMAGE.png',
                             'control_refs': ['c0001', 'c0002']}}
    return records, state


class ExplorationPurposeTests(unittest.TestCase):
    def test_observation_knowledge_and_actual_doubts_survive_projection(self):
        records, state = purpose_fixture()
        control = owned_controls(records['r0001'])['c0001']
        # A prior accepted fact must not hide a later observation-based fact.
        control_knowledge.update(control, [{'description': '最大化后可恢复原窗口大小。'}],
                                 {'task_ref': 'r0001/旧窗口问题', 'source_call': 'offline_prior'})
        doubt = '特殊布局下是否保留侧栏尚不清楚。'
        control_knowledge.update(control, [{'description': doubt}],
                                 {'source_call': 'offline_later', 'basis': 'observation_only'})
        before = control_knowledge.evidence(control)
        rendered = purpose_text(control)
        material = project(records, state, 'r0001')['控件']
        for fact in ('将当前窗口最大化。', '最大化后可恢复原窗口大小。', doubt):
            self.assertIn(fact, rendered)
            self.assertIn(fact, material)
        for false_label in ('未探索。', '推测用途', '功能尚未确认'):
            self.assertNotIn(false_label, rendered + material)
        self.assertIn('知识条目 0', material)
        self.assertIn('知识条目 2', material)
        self.assertEqual(control_knowledge.evidence(control), before)
        self.assertEqual(len(control_knowledge.confirmed(control)), 1)

    def test_observation_can_support_function_without_creating_execution(self):
        records = Records({'r0001': {'id': 'r0001', 'name': '示例窗口', 'description': '离线示例。',
                                     'controls': {'c0001': {'name': '最大化窗口', 'knowledge': []}},
                                     'tasks': {}}})
        object_knowledge.apply(records, {
            'controls': [{'ref': 'c0001', 'knowledge': [{'description': '将当前窗口最大化。'}]}],
            'function_updates': [{'region': 'r0001', 'add': [{
                'name': '最大化窗口', 'description': '将当前窗口最大化。', 'supports': ['c0001']}]}],
        }, {'source_call': 'offline_observation', 'basis': 'observation_only'})
        region = records['r0001']
        self.assertIn('最大化窗口', region['functions'])
        self.assertEqual(region['functions']['最大化窗口']['support_controls'][0]['control'], 'c0001')
        self.assertFalse(owned_actions(region))
        self.assertFalse(owned_tasks(region))
        self.assertFalse(control_knowledge.confirmed(owned_controls(region)['c0001']))
        self.assertFalse(owned_controls(region)['c0001'].get('jump_to'))

    def test_clear_entry_usage_does_not_remove_unknown_destination_candidate(self):
        from regrow.traversal.task_proposer import plan_request
        records, state = purpose_fixture()
        request = plan_request(ROOT, records, state, 'r0001')
        candidates = request['response_schema']['properties']['operations']['items']['properties']['control']['enum']
        self.assertIn('c0002', candidates)
        self.assertIn('面板内提供哪些功能尚不清楚', request['user_prompt'])
        self.assertNotIn('未探索。', request['user_prompt'])
        self.assertNotIn('推测用途', request['user_prompt'])
        self.assertFalse(owned_tasks(records['r0001']))


if __name__ == '__main__':
    unittest.main()
