"""Read-only multi-run browser view using the runs' pinned stepwise projections."""
import argparse
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit
try:
    from . import stepwise_dashboard_view as task_view
except ImportError:
    import stepwise_dashboard_view as task_view


def read(path):
    return json.loads(Path(path).read_text())


def accounting(sessions):
    """Include in-flight native round counters once, before session settlement."""
    http = gui = reviewed = 0
    latest = None
    for file in sorted(Path(sessions).glob('session-*/session.json')):
        value = read(file)
        http += value['http_started']
        gui += value['gui_started']
        if value['status'] == 'running':
            settled = set(value.get('rounds', []))
            for budget in file.parent.glob('round-*/budget.json'):
                if budget.parent.name not in settled:
                    counters = read(budget)
                    http += counters['http_started']
                    gui += counters['gui_started']
        review = file.parent / 'root-review.json'
        decision = read(review) if review.exists() else None
        accepted = decision is not None and decision.get('accepted', decision.get('continue')) is True
        continuing = decision is not None and decision.get('continue') is True
        reviewed += int(decision is not None)
        latest = {'name': file.parent.name, 'status': value['status'], 'reviewed': decision is not None,
                  'review_state': ('accepted' if accepted else 'continued_with_issue' if continuing else 'held') if decision else 'pending',
                  'review_reason': decision.get('reason', '') if decision else ''}
    return {'http': http, 'gui': gui, 'reviewed_steps': reviewed, 'latest': latest}


def server(config):
    source = Path(config['source']).resolve()
    sys.path[:0] = [str(source), str(Path(config['repository']).resolve())]
    import region_graph
    import region_tasks
    from region_tasks import effective_task
    # Presentation fixes apply to existing runs without editing their frozen source.
    # Task status/coverage still use the run's pinned implementation.
    display_path = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919/progress.py'
    spec = importlib.util.spec_from_file_location('dashboard_progress', display_path)
    progress = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(progress)
    from run_source import source_hash
    expected = source_hash(source)
    if config['source_hash'] != expected:
        raise ValueError('Dashboard source differs from the configured frozen source')
    apps = {item['key']: item for item in config['apps']}
    if not apps or any(not re.fullmatch(r'[a-z0-9_-]+', key) for key in apps):
        raise ValueError('Application keys must be simple URL identifiers')
    for item in apps.values():
        manifest = read(Path(item['run']) / 'run_manifest.json')
        if Path(manifest['framework_source']).resolve() != source:
            raise ValueError('Dashboard source must match each pinned run')

    def project(item):
        run = Path(item['run'])
        graph = region_graph.project(run)
        view = progress.snapshot(run, tasks=region_tasks)
        # Publishing may advance while the two existing projections are read.
        # Retry once, then report a transient gap instead of mixing snapshots.
        if graph['snapshot'] != view['snapshot']:
            graph = region_graph.project(run)
            view = progress.snapshot(run, tasks=region_tasks)
        if graph['snapshot'] != view['snapshot']:
            raise ValueError('Snapshot is advancing; retry on next refresh')
        frame_meta = read(run / 'live_frame.json') if (run / 'live_frame.json').exists() else {}
        return {'label': item['label'], 'graph': graph, 'progress': view,
                'focus': task_view.project(run, view, effective_task),
                'accounting': accounting(item['sessions']), 'limits': item['limits'],
                'frame_time': frame_meta.get('captured_at')}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            parts = parsed.path.strip('/').split('/')
            try:
                if parsed.path == '/':
                    body = Path(__file__).with_suffix('.html').read_bytes()
                    mime = 'text/html; charset=utf-8'
                elif parsed.path == '/apps.json':
                    body = json.dumps([{'key': k, 'label': v['label']} for k, v in apps.items()], ensure_ascii=False).encode()
                    mime = 'application/json; charset=utf-8'
                elif len(parts) == 2 and parts[1] in apps:
                    endpoint, key = parts
                    item = apps[key]
                    if endpoint == 'api':
                        body = json.dumps(project(item), ensure_ascii=False).encode()
                        mime = 'application/json; charset=utf-8'
                    elif endpoint == 'frame':
                        body = (Path(item['run']) / 'live_frame.png').read_bytes()
                        mime = 'image/png'
                    elif endpoint == 'image':
                        args = parse_qs(parsed.query)
                        file = region_graph.asset(item['run'], args['snapshot'][0], args['region'][0], args.get('control', [None])[0])
                        body = file.read_bytes()
                        mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(file.suffix.lower(), 'image/png')
                    elif endpoint == 'evidence':
                        args = parse_qs(parsed.query)
                        file = task_view.evidence_asset(item['run'], args['attempt'][0], args['frame'][0])
                        body = file.read_bytes()
                        mime = 'image/png'
                    else:
                        self.send_error(404)
                        return
                else:
                    self.send_error(404)
                    return
            except (OSError, ValueError, KeyError):
                self.send_error(503, 'Evidence temporarily unavailable')
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            self.send_error(405, 'This projection is read-only')

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(('127.0.0.1', config.get('port', 0)), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    service = server(read(args.config))
    print(json.dumps({'url': f'http://127.0.0.1:{service.server_port}/'}, ensure_ascii=False), flush=True)
    service.serve_forever()
