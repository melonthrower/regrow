"""Local editing and review snapshots for human prompt drafts, never traversal source."""
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
from threading import RLock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import prompt_review_trace as trace_tool
import prompt_review_work as work_tool

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


def related_prompts(request, paths):
    names = [part.get('path', '').split('/片段-', 1)[0] for part in request.get('fixed_parts', [])]
    return list(dict.fromkeys(name for name in names if name in paths))


def import_context(root, run, call, title):
    """Freeze one saved framework request and its actual images for human review."""
    root, run = Path(root).resolve(), Path(run).resolve()
    folder = run / 'calls' / call
    raw = (folder / 'request.json').read_bytes()
    request = json.loads(raw)
    user, system = (folder / 'user.prompt').read_bytes(), (folder / 'system.prompt').read_bytes()
    if user.decode() != request['user_prompt'] or system.decode() != request['system_prompt']:
        raise ValueError('保存的正文与request.json不一致，不能作为同一请求载入。')
    key = 'request-' + sha256(raw).hexdigest()[:16]
    destination = root / 'context_sources' / key
    frames = []
    for index, value in enumerate(request.get('screenshots', [])):
        path = Path(value)
        path = path if path.is_absolute() else run / path
        data = path.read_bytes()
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('请求附图格式不受支持。')
        frames.append((f'frame-{index + 1}{path.suffix.lower()}', data, str(path.resolve())))
    catalog_path = root / 'context_cases.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
    if key in catalog:
        return key
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in [('request.json', raw), ('user.prompt', user), ('system.prompt', system)]:
        (destination / name).write_bytes(content)
    images = []
    for name, content, source in frames:
        (destination / name).write_bytes(content)
        images.append({'file': name, 'sha256': sha256(content).hexdigest(), 'source': source})
    catalog[key] = {'id': key, 'title': title, 'call': call, 'role': request.get('role'),
                    'original_run': str(run), 'request_sha256': sha256(raw).hexdigest(),
                    'images': images,
                    'related_prompts': related_prompts(request, source_paths(root))}
    dump(catalog_path, catalog)
    return key


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
        self.workspace = sha256(str(self.root).encode()).hexdigest()[:16]

    def contexts(self):
        path = self.root / 'context_cases.json'
        cases = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        for case in cases.values():
            request = json.loads((self.root / 'context_sources' / case['id'] / 'request.json').read_text())
            case['related_prompts'] = related_prompts(request, self.paths)
        return cases

    def history_guide(self, name):
        """Human-only source notes; never part of draft text or model input."""
        catalog = json.loads((ASSETS / 'history_guide.json').read_text(encoding='utf-8'))
        if name.startswith('context:'):
            return {'notice': '这里是当次实际发送的上下文；历史按当时的代码选择，不用今天的实现倒推。',
                    'profiles': [{'title': '这份真实请求的历史', 'fields': {
                        '提供什么': '左侧保留当次完整 user prompt，页面上方可展开同次 system prompt，并查看原始附图。',
                        '如何核对': '在原文中查看身份候选、任务、执行记录和来源。右侧修改的是讨论稿，原件保持不变。',
                        '继续检查': '通过上方关联提示查看各部分当前的历史提供方式；它与这份旧请求可能不同。'}}],
                    'examples': [], 'stale_sources': []}
        keys = catalog['parts'].get(name, [])
        profiles = [deepcopy(catalog['profiles'][key]) for key in keys]
        stale = set()
        for profile in profiles:
            for source in profile.get('sources', []):
                path = ASSETS.parents[1] / source['file']
                if not path.exists() or sha256(path.read_bytes()).hexdigest() != source['sha256']:
                    stale.add(source['file'])
        examples = [case for case in self.contexts().values() if name in case.get('related_prompts', [])]
        return {'notice': catalog['notice'], 'profiles': profiles, 'examples': examples,
                'stale_sources': sorted(stale)}

    def read(self, name):
        with self.lock:
            if not isinstance(name, str):
                raise ValueError('请选择页面中已有的材料。')
            case = self.contexts().get(name.removeprefix('context:')) if name.startswith('context:') else None
            if name not in self.paths and case is None:
                raise ValueError('请选择页面中已有的提示段落。')
            record = self.records.get(name, {})
            if case:
                source = self.root / 'context_sources' / case['id']
                base = (source / 'user.prompt').read_text(encoding='utf-8')
                text = record.get('text', base)
                extra = {'kind': 'context', 'case': case,
                         'system_prompt': (source / 'system.prompt').read_text(encoding='utf-8')}
            else:
                text = self.paths[name].read_text(encoding='utf-8')
                base = record.get('base', text)
                extra = {'kind': 'prompt'}
            notes, idea = record.get('notes', []), record.get('idea', '')
            version = sha256(json.dumps([text, idea, notes], ensure_ascii=False).encode()).hexdigest()
            return {'path': name, 'text': text, 'base': base, **extra,
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
            if current['kind'] == 'prompt':
                path = self.paths[name]
                temporary = path.with_suffix('.new')
                temporary.write_text(text, encoding='utf-8')
                temporary.replace(path)
                build_data(self.root)
            return self.read(name)

    def read_worklog(self):
        with self.lock:
            path = self.data / 'worklog.md'
            text = path.read_text(encoding='utf-8') if path.exists() else ''
            return {'text': text, 'version': sha256(text.encode()).hexdigest(),
                    'workspace': self.workspace,
                    'saved_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else None}

    def save_worklog(self, value):
        with self.lock:
            current = self.read_worklog()
            if value.get('version') != current['version']:
                raise Conflict('工作记录已有较新版本；你的草稿保留在浏览器中，请先对照。')
            text = value['text']
            if not isinstance(text, str):
                raise ValueError('工作记录需要是文字。')
            if text != current['text']:
                key = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
                dump(self.data / 'worklog_history' / (key + '.json'),
                     {'before': current['text'], 'after': text, 'saved_at': datetime.now(timezone.utc).isoformat()})
                path = self.data / 'worklog.md'
                temporary = path.with_suffix('.new')
                temporary.write_text(text, encoding='utf-8')
                temporary.replace(path)
            return self.read_worklog()

    def submit(self, selected_contexts=()):
        with self.lock:
            edited = [self.read(name) for name in self.records]
            edited = [row for row in edited if row['changes'] or row['idea'].strip()
                      or any(note['body'].strip() for note in row['notes'])]
            selected = [self.read('context:' + key) for key in selected_contexts]
            contextual = {row['path']: row for row in [*selected, *edited] if row['kind'] == 'context'}
            worklog = self.read_worklog()
            if not edited and not contextual and not worklog['text'].strip():
                raise ValueError('还没有修改或想法；写好后再准备审查。')
            key = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:6]
            folder = self.data / 'submissions' / key
            # Separate author intent from independent first reading.
            dump(folder / 'prompts.json', {name: self.read(name)['text'] for name in self.paths})
            dump(folder / 'changes.json', [{k: row[k] for k in ('path', 'base', 'text', 'version', 'changes')} for row in edited if row['kind'] == 'prompt'])
            dump(folder / 'contexts.json', [{k: row[k] for k in ('path', 'base', 'text', 'version', 'changes', 'case')} for row in contextual.values()])
            for row in contextual.values():
                shutil.copytree(self.root / 'context_sources' / row['case']['id'], folder / 'context_sources' / row['case']['id'])
            dump(folder / 'ideas.json', [{k: row[k] for k in ('kind', 'path', 'idea', 'notes')} for row in edited])
            (folder / 'worklog.md').write_text(worklog['text'], encoding='utf-8')
            dump(folder / 'status.json', {'status': 'prepared', 'automatic_review_started': False, 'id': key})
            (folder / 'README.txt').write_text(
                '这是网页草稿快照，不代表运行框架已修改。\n'
                '先让新陌生读者阅读prompts.json、changes.json及contexts.json和所附归档图片，独立记录其理解和问题；'
                '随后再读ideas.json与worklog.md，对照作者想法，另存结论。\n'
                '上下文候选是讨论稿；原始请求和附图完整保留。未重建正常框架请求，不作为Luna验收或新GUI执行证据。\n'
                '浏览器未启动审查。用户在对话请求后，由主代理读取本快照并安排读者。\n', encoding='utf-8')
            return {'id': key, 'request': '请让陌生读者审查我在浏览器提交的修改，审查编号：' + key,
                    'count': len({row['path'] for row in edited} | set(contextual)), 'has_worklog': bool(worklog['text'].strip()), 'automatic_review_started': False}


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
        if route.path.startswith('/api/trace'):
            try:
                args = parse_qs(route.query)
                if route.path == '/api/trace':
                    self.respond({'traces': trace_tool.overview(self.store.root), 'jobs': trace_tool.jobs(self.store.root)})
                elif route.path == '/api/trace/current':
                    self.respond(work_tool.current_display(self.store.root,args['trace'][0],args['call'][0],self.store))
                elif route.path == '/api/trace/work':
                    self.respond(work_tool.view(self.store.root, args['trace'][0], self.store))
                elif route.path == '/api/trace/batch':
                    self.respond(work_tool.batch_view(self.store.root, args['trace'][0], args['id'][0]))
                elif route.path == '/api/trace/step':
                    self.respond(trace_tool.step(self.store.root, args['trace'][0], args['call'][0]))
                elif route.path == '/api/trace/job':
                    self.respond(trace_tool.job_view(self.store.root, args['id'][0]))
                elif route.path == '/api/trace/job-image':
                    path = trace_tool.job_image(self.store.root, args['id'][0], args['index'][0])
                    body = path.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', self.guess_type(str(path)))
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                elif route.path == '/api/trace/image':
                    path = trace_tool.image_path(self.store.root, args['trace'][0], args['call'][0], args['index'][0])
                    body = path.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', self.guess_type(str(path)))
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                else:
                    self.respond({'error': '未知轨迹接口'}, 404)
            except (ValueError, KeyError, IndexError, StopIteration, OSError) as error:
                self.respond({'error': str(error)}, 400)
            return
        if route.path == '/api/editor':
            name = parse_qs(route.query).get('path', [next(iter(self.store.paths))])[0]
            try:
                self.respond({'paths': list(self.store.paths), 'document': self.store.read(name),
                              'contexts': list(self.store.contexts().values()), 'workspace': self.store.workspace,
                              'history_guide': self.store.history_guide(name)})
            except ValueError as error:
                self.respond({'error': str(error)}, 400)
            return
        if route.path == '/api/editor/worklog':
            self.respond(self.store.read_worklog())
            return
        if route.path == '/api/editor/context-image':
            query = parse_qs(route.query)
            try:
                key = query['id'][0]
                case = self.store.contexts()[key]
                index = int(query['index'][0])
                if not 0 <= index < len(case['images']):
                    raise ValueError('unknown image')
                path = self.store.root / 'context_sources' / key / case['images'][index]['file']
                body = path.read_bytes()
            except (KeyError, IndexError, ValueError):
                self.respond({'error': '没有这张归档图片。'}, 404)
                return
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(path)))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route.path in ('/editor', '/editor.js', '/editor.css', '/worklog.js', '/trace.js', '/trace.css', '/worktrace.js'):
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
        if route not in ('/api/editor/save', '/api/editor/submit', '/api/editor/worklog', '/api/trace/start', '/api/trace/work-save', '/api/trace/batch-start', '/api/trace/adopt'):
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
            if route in ('/api/trace/work-save', '/api/trace/batch-start', '/api/trace/adopt'):
                action={'/api/trace/work-save':work_tool.save,'/api/trace/batch-start':work_tool.batch_start,'/api/trace/adopt':work_tool.adopt}[route]
                self.respond(action(self.store.root,value,self.store))
                return
            if route == '/api/trace/start':
                self.respond(trace_tool.start(self.store.root, value, self.store))
                return
            result = self.store.save(value) if route.endswith('/save') else self.store.save_worklog(value) if route.endswith('/worklog') else self.store.submit(value.get('contexts', []))
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
