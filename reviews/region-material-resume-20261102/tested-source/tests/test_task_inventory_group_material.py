"""Task material groups existing evidence without promoting it to shared success."""
from regrow.records.task_inventory_context import control_directory
from regrow.recognition.named_references import text as readable


def test_grouped_material_keeps_sources_and_deduplicates_only_equal_content():
    text = readable(control_directory({
        'c1': '用途：打开文档。',
        'c2': '知识条目 0：点击可打开文件。',
        'c3': '知识条目 0：点击可打开文件。',
        'c4': '知识条目 0：需要密码，尚未打开。',
    }, {'文件结果': ['c2', 'c3', 'c4']}),
        {'c1': '打开', 'c2': '文件甲', 'c3': '文件乙', 'c4': '文件丙'})
    assert text.index('未分组控件') < text.index('同类操作组')
    assert text.count('知识条目 0：点击可打开文件。') == 1
    assert '已有材料（文件甲、文件乙）' in text
    assert '需要密码，尚未打开' in text
    assert '共同机制已验证' not in text
    assert all(name in text for name in ['打开', '文件甲', '文件乙', '文件丙'])
