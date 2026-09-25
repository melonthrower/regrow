"""Carry durable task-inventory gaps into local control discovery."""
from pathlib import Path


def supplement(root, region, dynamic, parts):
    inventory=region.get('task_inventory',{})
    if inventory.get('inventory') not in ('partial','uncertain') or not inventory.get('evidence'):
        return
    dynamic['本区块待补登记']={
        '任务清点反馈':inventory['evidence'],
        '已登记控件数':len(region.get('controls',{})),
        '依据边界':'反馈来自历史清点，须结合当前截图核对；已有记录保留，不代表旧控件当前可见或已执行。',
    }
    path='发现手册/补登记.prompt'
    parts.append({'path':path,'text':(Path(root)/'遍历prompt'/path).read_text()})
