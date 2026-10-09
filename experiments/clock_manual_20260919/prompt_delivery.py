"""Select desktop rule sections and reference exact shared correction rules.

Only fixed instructions change; facts, schemas and archived requests stay intact.
"""
from pathlib import Path
import re


HOVER_SECTIONS = {
    'observation': {'发现阻塞', '外观登记'},
    'observation_update': {'外观登记', '更新观察'},
    'action_selection': {'动作观察'},
    'recovery': {'动作观察'},
    'task_proposal': {'任务清点'},
    'task_result_review': set(),
    'function_registration': set(),
}
ALIASES = {'discovery': 'observation', 'action': 'action_selection',
           'update': 'observation_update'}


def effective_role(request):
    if request.get('role') in ('step_correction', 'control_identity_selection') or request.get('stage') == 'correction':
        return effective_role(request.get('original_request', {}))
    role = request.get('role') or request.get('stage')
    return ALIASES.get(role, role)


def desktop_parts(root, request):
    role = effective_role(request)
    directory = Path(root) / '遍历prompt'
    for path in ('平台/桌面执行.prompt', '平台/桌面悬停观察.prompt'):
        text = (directory / path).read_text()
        if role in HOVER_SECTIONS:
            if path.endswith('桌面执行.prompt') and role not in ('action_selection', 'recovery'):
                text = text.partition('## 桌面键盘与鼠标')[0].rstrip()
            elif path.endswith('桌面悬停观察.prompt'):
                sections = re.split(r'(?m)(?=^### )', text)
                text = '\n\n'.join(section.strip() for section in sections
                    if not section.startswith('### ') or
                    section.splitlines()[0][4:] in HOVER_SECTIONS[role])
        yield {'path': path, 'text': text}


def original_rules(request, rules):
    """Remove only whole, identical fixed parts already present in system.

    Both requests must identify the same source part and exact text. A substring
    inside an unrelated paragraph or a changed version never counts as a copy.
    """
    original = request.get('original_request', {})
    common = {(part['path'], part['text']) for part in request.get('fixed_parts', [])}
    system = '\n\n' + request.get('system_prompt', '').strip() + '\n\n'
    remaining = '\n\n' + rules.strip() + '\n\n'
    references = []
    for part in original.get('fixed_parts', []):
        path, text = part['path'], part['text']
        block = '\n\n' + text.strip() + '\n\n'
        if (path, text) in common and block in system and block in remaining:
            remaining = remaining.replace(block, '\n\n')
            if path not in references: references.append(path)
    return (remaining.strip(), references) if references else (rules, [])
