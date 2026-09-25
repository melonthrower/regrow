from copy import deepcopy
from tests.test_stepwise_resume_route import ROOT, fixture


def test_tree_keeps_work_separate_from_location_and_navigation():
    m, records, state = fixture()
    before = deepcopy((records, state))
    request = m.assemble_context(ROOT, records, state, 'menu')
    tree = request['exploration_tree']
    assert tree == ''
    assert '最短已知路径（1 步）' in request['dynamic_prompt']
    assert '探索树' not in request['dynamic_prompt']
    assert (records, state) == before


def test_external_outcome_is_not_an_internal_branch_or_completion():
    m, records, state = fixture()
    state['interactive_regions'] = ['menu']
    control = records['menu']['controls']['open']
    control['action_refs'] = ['attempt']
    records['menu']['actions']['attempt'] = {
        'control': 'open', 'delivery': 'executed_receipt_zero',
        'result': {'exception': 'external_app', 'description': 'Chrome 欢迎页，政策内容未出现'},
        'evidence': {}}
    records['menu']['transitions'].append({
        'source_control': 'open', 'target_region': 'middle', 'attempt': 'attempt'})
    q = m.assemble_context(ROOT, records, state, 'menu')
    tree = q['exploration_tree']
    assert 'Chrome 欢迎页，政策内容未出现' in tree
    assert '当前观察已定位' not in tree
    assert '当前可交互' not in tree
    assert '→ 中间区' not in tree
    assert '已探索完成' not in tree
    assert 'attempt' not in tree
    assert any(p['path'] == '历史上下文/探索树阅读.prompt' for p in q['fixed_parts'])


def test_tree_collapses_excess_controls_without_claiming_complete():
    m, records, state = fixture()
    state['interactive_regions'] = ['menu']
    for n in range(20):
        records['menu']['controls'][str(n)] = {
            'name': f'选项{n}', 'observations': [], 'action_refs': []}
    tree = m.assemble_context(ROOT, records, state, 'menu')['exploration_tree']
    assert '另有 13 个已登记控件折叠' in tree
    assert '不代表探索完成' in tree
    state['action_history_supplied'] = False
    tree = m.assemble_context(ROOT, records, state, 'menu')['exploration_tree']
    assert '未提供动作历史' in tree


def test_observed_navigation_is_folded_and_never_recursively_expanded():
    m, records, state = fixture()
    records['main']['controls']['open']['action_refs'] = ['a1', 'a3']
    records['main']['transitions'].append(deepcopy(records['main']['transitions'][0]))
    state['working_region'] = 'main'
    tree = m.assemble_context(ROOT, records, state, 'main')['exploration_tree']
    assert tree.count('已观察跳转 → 中间区') == 1
    assert '已观察跳转 → 菜单' in tree
    assert '打开中间区' not in tree
    assert '打开菜单' not in tree
