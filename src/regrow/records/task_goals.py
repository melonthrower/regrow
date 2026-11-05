"""Construct a bounded question once; later stages read its stored endpoint."""
from copy import deepcopy


def operation_schema():
    from regrow.records.task_updates import object_schema
    text = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    value = object_schema({
        'control': {'type': 'string'},
        'task_type': {'type': 'string', 'enum': ['function', 'parameter', 'region_content']},
        'template': {'type': 'string', 'enum': ['entry', 'choices', 'input', 'effect', 'content', 'custom']},
        'reason': {**text, 'description': '本题帮助了解哪项主要功能或必要参数，并补充什么认识；已有相关问题或同类用法时，说明具体未覆盖的功能或条件差异。未亲点、名称或组名不同本身不足以立题。'}})
    value['properties'].update(question=deepcopy(text), condition=deepcopy(text), completion_condition=deepcopy(text))
    rules = [(['entry', 'effect'], {'properties': {'task_type': {'const': 'function'}, 'question': False, 'completion_condition': False}}),
             (['choices', 'input'], {'required': ['question'], 'properties': {'task_type': {'const': 'parameter'}, 'completion_condition': False}}),
             (['content'], {'required': ['question'], 'properties': {'task_type': {'const': 'region_content'}, 'control': {'const': ''}, 'completion_condition': False}}),
             (['custom'], {'required': ['question', 'completion_condition'], 'properties': {'condition': False}})]
    value['allOf'] = [{'if': {'properties': {'template': {'enum': names}}, 'required': ['template']}, 'then': rule}
                      for names, rule in rules]
    value['allOf'].append({'if': {'properties': {'task_type': {'const': 'region_content'}}, 'required': ['task_type']},
                           'then': {'properties': {'control': {'const': ''}}},
                           'else': {'properties': {'control': {'minLength': 1, 'pattern': r'\S'}}}})
    return value


def normalize(operation, control_name, region_name):
    """Expand an already validated proposal; keep no parallel Task template."""
    task = deepcopy(operation)
    template = task.pop('template')
    question = task.pop('question', '')
    condition = task.pop('condition', '')
    label = control_name or region_name
    if template == 'entry':
        goal = f'查看「{label}」打开的直接内容。完成：入口已打开且直接内容已看清；若真实观察明确该控件不打开内容，则已说明实际直接作用和推翻入口假设的依据。'
    elif template == 'choices':
        goal = f'查看并登记「{label}」的{question}。完成：该范围内有限候选已收齐并登记，不要求逐个应用。'
    elif template == 'input':
        goal = f'弄清「{label}」的{question}。完成：所问规则已明确并登记，不要求穷举取值或测试未问边界。'
    elif template == 'effect':
        goal = f'弄清「{label}」直接执行的功能。完成：直接作用已明确并登记，不要求完成所属业务流程。'
    elif template == 'content':
        goal = f'查看「{label}」的{question}。完成：该范围已查看，发现的信息按所属对象登记；同类业务实例复用共同用法。'
    else:
        goal = question + '。完成：' + task['completion_condition']
    task['completion_condition'] = ('在「' + condition + '」条件下：' if condition else '') + goal
    return task
