"""New questions keep their exact target; old records retain their old goals."""


def operation_schema():
    from regrow.records.task_updates import object_schema
    value = object_schema({'control': {'type': 'string'},
                           'target': {'type': 'string', 'minLength': 1, 'pattern': r'\S'},
                           'function_refs': {'type': 'array', 'uniqueItems': True,
                                             'items': {'type': 'string', 'minLength': 1}}})
    value['required'] = ['control', 'target']
    return value


def legacy_definition(kind):
    label, goal = {
        'function': ('功能探索', '了解控件尚不明确的直接作用或入口内容。'),
        'parameter': ('参数探索', '弄清选择部件尚未知的有限候选或所问填写规则。'),
        'region_content': ('区块内容探索', '查看本区块尚未显示的内容。'),
    }[kind]
    return {'label': label, 'goal': goal, 'region_goal': goal}
