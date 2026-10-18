"""Single executable source root, including frozen run sources."""
import runpy
import sys

ENTRIES = {
    'session': 'regrow.traversal.run_progress_session',
    'step': 'regrow.traversal.run_task_step',
    'launch': 'regrow.tools.launch_traversal',
    'batch': 'regrow.tools.batch_launch',
    'batch-worker': 'regrow.runtime.batch_runtime',
    'inspect': 'regrow.tools.render_region_context',
}

if __name__ == '__main__':
    command = sys.argv.pop(1) if len(sys.argv) > 1 else 'launch'
    if command not in ENTRIES:
        raise SystemExit('入口必须是：' + ', '.join(ENTRIES))
    runpy.run_module(ENTRIES[command], run_name='__main__')
