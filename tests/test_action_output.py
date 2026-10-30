from regrow.prompts.call_examples import sections, local_sections
from regrow.records.function_updates import schema as functions


def test_empty_control_catalog_still_allows_region_answer_examples():
    fields = {'action': {'type': 'string', 'enum': ['complete']},
              'reason': {'type': 'string'},
              'controls': {'type': 'array', 'items': {'type': 'object',
                  'properties': {'index': {'type': 'integer', 'enum': []},
                                 'knowledge': {'type': 'array'}},
                  'required': ['index', 'knowledge']}},
              'function_updates': functions(['r0043'])}
    schema = {'anyOf': [{'type': 'object', 'properties': fields,
                         'required': ['action', 'reason'], 'additionalProperties': False}]}
    rendered = sections(schema)
    assert '未开放controls' in rendered['控件知识格式']
    assert 'r0043' in rendered['功能更新格式']
    assert '已有答案' not in rendered['控件知识格式']
    task_schema = {'type': 'object', 'properties': {'operations': {
        'type': 'array', 'items': {'type': 'object', 'properties': {
            'control': {'type': 'string', 'enum': ['']},
            'task_type': {'type': 'string', 'enum': ['function', 'parameter', 'region_content']}},
            'required': ['control', 'task_type']}}}}
    empty = local_sections(task_schema, {}, {'探索任务正例'})
    assert '"operations": []' in empty['探索任务正例']
