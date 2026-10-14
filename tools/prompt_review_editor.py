"""Local editing and review snapshots for human prompt drafts, never traversal source."""
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import RLock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ASSETS = Path(__file__).with_suffix('')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def source_paths(root):
    names = json.loads((root / 'catalog-manifest.json').read_text(encoding='utf-8'))['sources']
    return {name: root / 'dist' / ('drafts/术语定义-历史权衡稿.prompt.txt'
            if name == '共享/术语定义.prompt' else 'modified/' + name + '.txt') for name in names}


def build_data(root):
    """The existing two-column page and editor share the same draft source files."""
    root = Path(root)
    original, modified = {}, {}
    for name, path in source_paths(root).items():
        old = root / 'dist/sources' / (name + '.txt')
        original[name] = {'text': old.read_text(encoding='utf-8'), 'href': 'sources/' + name + '.txt'}
        modified[name] = {'text': path.read_text(encoding='utf-8'), 'href': str(path.relative_to(root / 'dist'))}
    for filename, variable, data in [('original.js', 'REGROW_ORIGINAL', original),
                                     ('modified.js', 'REGROW_MODIFIED', modified)]:
        text = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
        path = root / 'dist' / filename
        temporary = path.with_suffix('.new')
        temporary.write_text('window.' + variable + ' = ' + text + ';\n', encoding='utf-8')
        temporary.replace(path)


def changes(before, after):
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    rows = []
    for kind, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if kind == 'equal':
            continue
        section_lines = old[:a + 1] if kind == 'delete' else new[:c + 1]
        heading = next((line.strip() for line in reversed(section_lines) if line.startswith('#')), '')
        rows.append({'kind': kind, 'section': heading,
                     'before': {'start_line': a + 1, 'end_line': b, 'text': ''.join(old[a:b])},
                     'after': {'start_line': c + 1, 'end_line': d, 'text': ''.join(new[c:d])}})
    return rows


class Conflict(Exception):
    pass


class EditorStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.paths = source_paths(self.root)
        self.data = self.root / 'user_edits'
        self.state_path = self.data / 'state.json'
        self.records = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}
        self.lock = RLock()

    def read(self, name):
        with self.lock:
            if name not in self.paths:
                raise ValueError('请选择页面中已有的提示段落。')
            text = self.paths[name].read_text(encoding='utf-8')
            record = self.records.get(name, {})
            notes, idea = record.get('notes', []), record.get('idea', '')
            version = sha256(json.dumps([text, idea, notes], ensure_ascii=False).encode()).hexdigest()
            return {'path': name, 'text': text, 'base': record.get('base', text),
                    'idea': idea, 'notes': deepcopy(notes), 'version': version,
                    'saved_at': record.get('saved_at'), 'changes': changes(record.get('base', text), text)}

    def save(self, value):
        with self.lock:
            name = value['path']
            current = self.read(name)
            if value.get('version') != current['version']:
                raise Conflict('这段内容已在其他页面更新。你的输入仍保留，请先与最新内容对照。')
            text, idea, notes = value['text'], value.get('idea', ''), value.get('notes', [])
            if not isinstance(text, str) or not isinstance(idea, str) or not isinstance(notes, list):
                raise ValueError('正文和想法需要是文字。')
            clean_notes = []
            for note in notes:
                if not all(isinstance(note.get(k), str) for k in ('id', 'body', 'quote', 'source_text')):
                    raise ValueError('选中文字的说明不完整。')
                a, b = note.get('start_line'), note.get('end_line')
                if not isinstance(a, int) or not isinstance(b, int) or not 1 <= a <= b:
                    raise ValueError('选中文字的位置无效。')
                lines = note['source_text'].splitlines(keepends=True)
                if b > len(lines) or not note['quote'] or note['quote'] not in ''.join(lines[a - 1:b]):
                    raise ValueError('标注原文与记录的位置不符。')
                clean_notes.append({k: note[k] for k in ('id', 'body', 'quote', 'source_text', 'start_line', 'end_line')})
            if (text, idea, clean_notes) == (current['text'], current['idea'], current['notes']):
                return current
            stamp = datetime.now(timezone.utc).isoformat()
            event = {'path': name, 'saved_at': stamp, 'before': current['text'], 'after': text,
                     'changes': changes(current['text'], text), 'idea': idea, 'notes': clean_notes}
            event_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
            dump(self.data / 'history' / (event_id + '.json'), event)
            record = {'base': current['base'], 'text': text, 'idea': idea, 'notes': clean_notes, 'saved_at': stamp}
            self.records[name] = record
            dump(self.state_path, self.records)
            path = self.paths[name]
            temporary = path.with_suffix('.new')
            temporary.write_text(text, encoding='utf-8')
            temporary.replace(path)
            build_data(self.root)
            return self.read(name)

    def submit(self):
        with self.lock:
            edited = [self.read(name) for name in self.records]
            edited = [row for row in edited if row['changes'] or row['idea'].strip()
                      or any(note['body'].strip() for note in row['notes'])]
            if not edited:
                raise ValueError('还没有修改或想法；写好后再准备审查。')
            key = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:6]
            folder = self.data / 'submissions' / key
            # Separate author intent from independent first reading.
            dump(folder / 'prompts.json', {name: self.read(name)['text'] for name in self.paths})
            dump(folder / 'changes.json', [{k: row[k] for k in ('path', 'base', 'text', 'version', 'changes')} for row in edited])
            dump(folder / 'ideas.json', [{k: row[k] for k in ('path', 'idea', 'notes')} for row in edited])
            dump(folder / 'status.json', {'status': 'prepared', 'automatic_review_started': False, 'id': key})
            (folder / 'README.txt').write_text(
                '这是网页草稿快照，不代表运行框架已修改。\n'
                '先让新陌生读者阅读prompts.json与changes.json，独立记录其理解和问题；'
                '随后再读ideas.json，对照作者想法，另存结论。\n'
                '浏览器未启动审查。用户在对话请求后，由主代理读取本快照并安排读者。\n', encoding='utf-8')
            return {'id': key, 'request': '请让陌生读者审查我在浏览器提交的修改，审查编号：' + key,
                    'count': len(edited), 'automatic_review_started': False}


class EditorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, store, **kwargs):
        self.store = store
        super().__init__(*args, directory=str(store.root / 'dist'), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def guess_type(self, path):
        kind = super().guess_type(path)
        return kind + '; charset=utf-8' if kind.startswith('text/') or kind == 'application/json' else kind

    def respond(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path)
        if route.path == '/api/editor':
            name = parse_qs(route.query).get('path', [next(iter(self.store.paths))])[0]
            try:
                self.respond({'paths': list(self.store.paths), 'document': self.store.read(name)})
            except ValueError as error:
                self.respond({'error': str(error)}, 400)
            return
        if route.path in ('/editor', '/editor.js', '/editor.css'):
            filename = 'editor.html' if route.path == '/editor' else route.path[1:]
            path = ASSETS / filename
            body = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(path)))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ('/api/editor/save', '/api/editor/submit'):
            self.respond({'error': '未知请求。'}, 404)
            return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' or self.headers.get_content_type() != 'application/json':
            self.respond({'error': '请从编辑页提交。'}, 403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2_000_000:
                raise ValueError('提交内容为空或过大。')
            value = json.loads(self.rfile.read(length))
            result = self.store.save(value) if route.endswith('/save') else self.store.submit()
            self.respond(result)
        except Conflict as error:
            self.respond({'error': str(error)}, 409)
        except (ValueError, KeyError, TypeError) as error:
            self.respond({'error': str(error)}, 400)


def make_server(root, port=45663):
    store = EditorStore(root)
    return ThreadingHTTPServer(('127.0.0.1', port), partial(EditorHandler, store=store))


def serve(root, port=45663):
    server = make_server(root, port)
    print(f'Prompt review editor: http://127.0.0.1:{server.server_port}/editor', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    serve(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 45663)
