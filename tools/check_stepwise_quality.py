"""Read-only stepwise graph quality: build, independently review, and visualize."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.stepwise_quality import evidence, review, view


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build', help='freeze existing run evidence; no model or GUI calls')
    build.add_argument('run', type=Path)
    build.add_argument('output', type=Path)
    build.add_argument('--calls', help='inclusive call interval, e.g. 0806:0827')
    inspect = sub.add_parser('review', help='explicitly invoke independent reviewer with its own budget')
    inspect.add_argument('output', type=Path)
    inspect.add_argument('backend', choices=['codex', 'luna'])
    inspect.add_argument('--budget', type=int, required=True)
    inspect.add_argument('--item', action='append', help='exact item ID; repeat to review selected evidence')
    serve = sub.add_parser('serve')
    serve.add_argument('output', type=Path)
    serve.add_argument('--port', type=int, default=0)
    human = sub.add_parser('feedback', help='import one human feedback JSON from portable page')
    human.add_argument('output', type=Path)
    human.add_argument('file', type=Path)
    a = p.parse_args()
    if a.command == 'build':
        calls = None
        if a.calls:
            first, last = (int(x) for x in a.calls.split(':'))
            if not 0 <= first <= last:
                p.error('invalid call interval')
            calls = [f'{i:04d}' for i in range(first, last + 1)]
        result = evidence.build(a.run, a.output, calls)
        view.export_page(a.output)
        print(json.dumps({'items': len(result['items']), 'page': str(a.output / 'index.html')}, ensure_ascii=False))
    elif a.command == 'review':
        result = review.run_checks(a.output, a.backend, a.budget, item_ids=a.item)
        view.export_page(a.output)
        print(json.dumps(result))
    elif a.command == 'feedback':
        view.feedback(a.output, evidence.read(a.file))
    else:
        app = view.server(a.output, a.port)
        print(json.dumps({'url': f'http://127.0.0.1:{app.server_port}/'}), flush=True)
        app.serve_forever()


if __name__ == '__main__':
    main()
