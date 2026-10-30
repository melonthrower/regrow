"""Focused regression checks for the 17-purpose prompt composition contract.

Run with: PYTHONPATH=src python -m unittest discover -s tests -p test_prompt_composition.py
Requires the same import dependencies as the normal request builders. These
checks do not test Luna's behavior and never call a model or control a GUI.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from prompt_composition_cases import cases, fixture_run, observation, update, SCOPE
from regrow.runtime.model_transport import prepare_request, expand_schema
from regrow.prompts.output import prepare, template_role
from regrow.prompts.compose import catalog, configuration_paths
from regrow.prompts.field_sections import _without_descriptions


ROOT = Path(__file__).resolve().parents[1] / 'src'


class PromptCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='regrow_prompt_test_')
        cls.fixture_dir = Path(cls.temp.name)
        cls.raw = cases(ROOT, cls.fixture_dir)
        cls.sent = {name: prepare_request(ROOT, cls.fixture_dir, deepcopy(q), q.get('platform', 'android'))
                    for name, q in cls.raw.items()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def q(self, prefix):
        return next(q for name, q in self.sent.items() if name.startswith(prefix + '_'))

    def test_every_configured_purpose_is_exercised(self):
        roles = {template_role(q, ROOT) for q in self.sent.values()}
        self.assertEqual(roles, set(catalog(ROOT)['calls']))
        self.assertEqual(len(roles), 17)
        for name, q in self.sent.items():
            with self.subTest(name=name):
                if q.get('correction_format') != 'original':
                    self.assertEqual(q['prompt_composition'], 'field_sections')

    def test_composition_never_changes_validation_contract(self):
        for name, q in self.sent.items():
            with self.subTest(name=name):
                before = deepcopy(q['response_schema'])
                self.assertEqual(prepare(deepcopy(q), ROOT)['response_schema'], before)

    def test_repeated_final_prepare_retains_rules_and_material(self):
        for name, q in self.sent.items():
            with self.subTest(name=name):
                second = prepare_request(ROOT, self.fixture_dir, deepcopy(q), q.get('platform', 'android'))
                self.assertEqual(second['system_prompt'], q['system_prompt'])
                self.assertEqual(second['user_prompt'], q['user_prompt'])
                self.assertEqual(expand_schema(second['response_schema']), expand_schema(q['response_schema']))
                paths = [p['path'] for p in q['fixed_parts']]
                self.assertEqual(len(paths), len(set(paths)))
                self.assertNotIn('{{', q['system_prompt'])

    def test_schema_annotation_removal_keeps_description_data(self):
        schema = {'description': 'annotation', 'type': 'object', 'properties': {
            'description': {'type': 'string', 'description': 'another annotation'}}, 'required': ['description']}
        result = _without_descriptions(schema)
        self.assertEqual(result['properties']['description'], {'type': 'string'})
        self.assertEqual(result['required'], ['description'])
        self.assertIn('description', schema)

    def test_narrow_calls_only_get_their_own_fields(self):
        for prefix in ('08', '13', '14', '15', '16'):
            with self.subTest(prefix=prefix):
                q = self.q(prefix)
                self.assertNotIn('action.proposal', q['prompt_sections'])
                self.assertNotIn('task.operations', q['prompt_sections'])
                self.assertNotIn('action.record_edit', q['prompt_sections'])
        self.assertEqual(set(expand_schema(self.q('15')['response_schema'])['properties']), {'evidence'})

    def test_conditional_geometry_and_task_shapes(self):
        self.assertIn('control.new_knowledge', self.q('01')['prompt_sections'])
        for prefix in ('02', '03', '06'):
            self.assertNotIn('control.new_knowledge', self.q(prefix)['prompt_sections'])
        self.assertIn('task.update_ref', self.q('04')['prompt_sections'])
        self.assertNotIn('task.update_ref', self.q('06')['prompt_sections'])
        self.assertNotIn('task.update', self.q('23')['prompt_sections'])
        self.assertNotIn('region.function_updates', self.q('23')['prompt_sections'])
        self.assertNotIn('bbox', self.q('04')['system_prompt'])
        self.assertNotIn('region.function_new_constraints', self.q('07')['prompt_sections'])

    def test_local_completion_and_dependency_fields_follow_actual_request(self):
        self.assertNotIn('region.focus_presence', self.q('01')['prompt_sections'])
        self.assertIn('region.focus_presence', self.q('22')['prompt_sections'])
        self.assertIn('region.local_registration', self.q('22')['prompt_sections'])
        self.assertNotIn('region.local_registration', self.q('01')['prompt_sections'])
        self.assertNotIn('region.local_registration', self.q('04')['prompt_sections'])
        self.assertIn('task.completion_updates', self.q('22')['prompt_sections'])
        self.assertNotIn('task.dependency_updates', self.q('01')['prompt_sections'])
        self.assertIn('task.dependency_updates', self.q('37')['prompt_sections'])
        self.assertIn('task.dependency_updates', self.q('38')['prompt_sections'])
        with tempfile.TemporaryDirectory(prefix='regrow_dependency_test_') as folder:
            fixture_run(folder, dependency=True)
            for raw in (observation(ROOT), update(ROOT)):
                q = prepare_request(ROOT, folder, raw)
                self.assertIn('task.dependency_updates', q['prompt_sections'])
                self.assertIn('dependency_updates', expand_schema(q['response_schema'])['properties'])
                self.assertIn('在本次 controls 中同时报告已解锁的目标控件', q['system_prompt'])
                self.assertIn('没有新依据时填 []', q['system_prompt'])
            # Same pipeline_step as observation, but a distinct purpose/stage.
            pure = deepcopy(next(q for n, q in self.raw.items() if n.startswith('07_')))
            pure['pipeline_step'] = 'discovery'
            q = prepare_request(ROOT, folder, pure)
            self.assertNotIn('task.dependency_updates', q['prompt_sections'])

    def test_task_proposal_keeps_legacy_name_with_task_meaning(self):
        q = self.q('02')
        self.assertIn('# 新增探索问题：operations', q['system_prompt'])
        self.assertNotIn('task.update', q['prompt_sections'])
        self.assertIn('task.update', self.q('20')['prompt_sections'])
        self.assertNotIn('shared_instances', self.q('20')['system_prompt'])
        self.assertIn('task.scope_review', self.q('39')['prompt_sections'])
        self.assertNotIn('task.scope_review', self.q('20')['prompt_sections'])

    def test_navigation_target_review_inherits_navigation_semantics(self):
        for prefix in ('18', '19', '27'):
            with self.subTest(prefix=prefix):
                q = self.q(prefix)
                self.assertIn('action.none_navigation', q['prompt_sections'])
                self.assertNotIn('action.none', q['prompt_sections'])
                self.assertNotIn('task.definition', q['prompt_sections'])
                self.assertNotIn('complete', q['system_prompt'])
        self.assertEqual(self.q('27')['response_schema'], self.q('27')['original_request']['response_schema'])
        for prefix in ('09', '27'):
            self.assertIn('| action | 需要填写的字段 | 操作含义 |', self.q(prefix)['system_prompt'])

    def test_nested_actions_and_platform_permissions(self):
        for prefix in ('10', '12', '25'):
            q = self.q(prefix)
            self.assertIn('`action.operation`', q['system_prompt'])
            self.assertNotIn('action.none', q['prompt_sections'])
            self.assertNotIn('action.complete', q['prompt_sections'])
        self.assertNotIn('recovery_handoff', self.q('12')['system_prompt'])
        self.assertIn('hover', self.q('25')['system_prompt'])
        from regrow.prompts.output import action_schema
        for prefix in ('12', '25'):
            _, value = action_schema(self.q(prefix)['response_schema'])
            actions = {a for b in value['anyOf'] for a in b['properties']['action']['enum']}
            self.assertNotIn('none', actions)
            self.assertEqual('hover' in actions, prefix == '25')

    def test_shared_review_is_not_ordinary_correction(self):
        q = self.q('11')
        self.assertEqual(template_role(q, ROOT), 'shared_control_review')
        self.assertNotIn('action.correction_decision', q['prompt_sections'])
        self.assertFalse(any(p['path'] == '平台/遍历环境只读.prompt' for p in q['fixed_parts']))
        value = expand_schema(q['response_schema'])['properties']
        self.assertEqual(value['proposal'], {'type': 'null'})
        self.assertNotIn('type', value['record_edit'])
        self.assertNotIn('array', str(value['record_edit']))
        self.assertIn('成员齐全、已有实际结果且均无异常', q['system_prompt'])

    def test_correction_permissions_and_original_contract(self):
        q = self.q('17')
        self.assertIn('action.correction_full', q['prompt_sections'])
        self.assertIn('action.record_edit_task', q['prompt_sections'])
        self.assertIn('字段之间的条件', q['system_prompt'])
        self.assertIn('record_edit', q['system_prompt'])
        sparse = self.q('28')
        self.assertIn('action.correction_partial', sparse['prompt_sections'])
        self.assertNotIn('action.correction_full', sparse['prompt_sections'])
        self.assertEqual(expand_schema(sparse['response_schema'])['properties']['proposal']['anyOf'][0]['minProperties'], 1)
        no_edit = self.q('29')
        self.assertNotIn('action.record_edit', no_edit['prompt_sections'])
        self.assertNotIn('record_edit', expand_schema(no_edit['response_schema'])['properties'])
        self.assertNotIn('字段之间的条件', no_edit['system_prompt'])
        self.assertNotIn('本次纠错/纠错/登记修订.prompt', [p['path'] for p in no_edit['fixed_parts']])
        self.assertIn('离线专用规则：保留本次额外核对要求。', self.q('32')['system_prompt'])
        for block in ('action.record_edit_basic', 'action.record_edit_task',
                      'action.record_edit_owner', 'action.record_edit_observation'):
            self.assertIn(block, self.q('33')['prompt_sections'])
        for prefix in ('34', '35'):
            narrow = self.q(prefix)
            self.assertNotIn('action.record_edit', narrow['prompt_sections'])
            self.assertNotIn('action.correction_observe', narrow['prompt_sections'])
            self.assertEqual(expand_schema(narrow['response_schema'])['properties']['resolution']['enum'],
                             ['revise', 'defer', 'blocked'])
        self.assertIn('右、下边界不含', self.q('34')['system_prompt'])
        self.assertIn('same/new 时均写清楚', self.q('35')['system_prompt'])
        self.assertIn('已保存的历史调用要求：按当时给定的对象范围作答。', self.q('36')['system_prompt'])

    def test_original_format_retry_is_unchanged(self):
        q = next(q for n, q in self.raw.items() if n.startswith('30_'))
        saved = deepcopy(q)
        self.assertIs(prepare(q, ROOT), q)
        self.assertIs(prepare_request(ROOT, self.fixture_dir, q), q)
        self.assertEqual(q, saved)

    def test_unsupported_branch_and_closed_arrays_hide_teaching(self):
        self.assertNotIn('task.branch_resume', self.q('16')['prompt_sections'])
        self.assertIn('task.branch_resume', self.q('26')['prompt_sections'])
        q = self.q('31')
        for block in ('control.knowledge_revision', 'region.knowledge_edit', 'region.function_updates'):
            self.assertNotIn(block, q['prompt_sections'])
        self.assertIn('本步的空字段', q['system_prompt'])
        self.assertNotIn('task.new_function_refs', q['prompt_sections'])
        self.assertNotIn('本次新增功能', q['system_prompt'])

    def test_unknown_new_root_fields_require_an_explicit_recipe(self):
        q = deepcopy(self.q('15'))
        q['response_schema']['properties']['unexplained_new_field'] = {'type': 'string'}
        with self.assertRaisesRegex(ValueError, '字段说明未覆盖'):
            prepare(q, ROOT)

    def test_editor_discovers_recipe_and_semantic_sources(self):
        from regrow.prompts.object_blocks import purpose
        self.assertEqual(purpose(ROOT, self.q('11')), 'shared_control_review')
        self.assertEqual(purpose(ROOT, self.q('17')), 'step_correction')
        self.assertEqual(purpose(ROOT, self.q('30')), 'observation')
        paths = configuration_paths(ROOT)
        text = str(paths)
        self.assertIn('流程/调用组成.json', text)
        for file in ('控件', '区块', '任务', '动作'):
            self.assertIn('对象/' + file + '.prompt', text)
        for name, q in self.sent.items():
            with self.subTest(name=name):
                self.assertEqual(q['system_prompt'].count('# 角色与目标'), 1)
                self.assertEqual(q['system_prompt'].count(SCOPE), 1)


if __name__ == '__main__':
    unittest.main()
