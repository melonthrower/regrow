"""Portable review page and localhost human-feedback service."""
import json
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .evidence import inside, read, write


def render(output, token=''):
    output = Path(output)
    data = json.dumps(read(output / 'report.json'), ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('viewer.html').read_text(encoding='utf-8')
    return template.replace('__REPORT_DATA__', data).replace('__REVIEW_TOKEN__', token)


def export_page(output):
    path = Path(output) / 'index.html'
    path.write_text(render(output), encoding='utf-8')
    return path


def feedback(output, value):
    if value.get('decision') not in ('agree', 'disagree', 'uncertain'):
        raise ValueError('invalid human decision')
    report = read(Path(output) / 'report.json')
    item = next((x for x in report['items'] if x['id'] == value.get('item_id')), None)
    if item is None:
        raise ValueError('unknown item')
    note = str(value.get('note', ''))
    if value['decision'] == 'disagree' and not note.strip():
        raise ValueError('否定需要简短说明')
    item['human'].append({'decision': value['decision'], 'note': note,
                          'at': datetime.now(timezone.utc).isoformat(),
                          'judgments_at_review': len(item['judgments'])})
    write(Path(output) / 'report.json', report)
    export_page(output)


def server(output, port=0):
    output = Path(output).resolve()
    token = secrets.token_hex(24)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path in ('/', '/index.html'):
                    data, mime = render(output, token).encode(), 'text/html; charset=utf-8'
                elif path == '/report.json':
                    data, mime = (output / 'report.json').read_bytes(), 'application/json'
                elif path.startswith('/assets/'):
                    target = inside(output / 'assets', output / path.lstrip('/'))
                    data = target.read_bytes()
                    mime = 'image/jpeg' if target.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
                else:
                    self.send_error(404)
                    return
            except (OSError, ValueError):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != '/feedback' or self.headers.get('X-Review-Token') != token:
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16000:
                    raise ValueError('invalid size')
                value = json.loads(self.rfile.read(size))
                with lock:
                    feedback(output, value)
            except (ValueError, TypeError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
