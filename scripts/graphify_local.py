"""Restricted Graphify adapter: allowlisted AST input, no network or child processes."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.cache/graphify-runtime'
CORPUS = RUNTIME / 'source'
OUTPUT = RUNTIME / 'graphify-out'
ALLOWED = ('backend/app', 'backend/tests', 'frontend/src', 'frontend/tests')
EXTENSIONS = {'.py', '.ts', '.tsx'}
VERSION = '0.9.103'
SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gsk_[A-Za-z0-9]{20,}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b')


def under(path, parent):
    return path == parent or parent in path.parents


def secrets():
    # Read locally before importing Graphify; never print values or pass them to it.
    values = []
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('\"\'')
            if re.search(r'KEY|TOKEN|SECRET|PASSWORD', key, re.I) and len(value) >= 12:
                values.append(value)
    return values


def check_text(text, values):
    if SECRET.search(text) or any(value in text for value in values):
        raise RuntimeError('Possible credential detected. Graph access stopped; no matched values are printed.')


def snapshot(values):
    files = {}
    for folder in ALLOWED:
        base = ROOT / folder
        for path in sorted(base.rglob('*')):
            if path.suffix not in EXTENSIONS or not path.is_file():
                continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if under(p, ROOT)) or not under(path.resolve(), base.resolve()):
                raise RuntimeError('Symlink input refused.')
            if path.stat().st_size > 2_000_000:
                raise RuntimeError('Source exceeds the 2 MB per-file ingestion limit.')
            raw = path.read_bytes()
            check_text(raw.decode('utf-8'), values)
            files[path.relative_to(ROOT).as_posix()] = raw
    return files


def restrict():
    # Provider credentials/config overrides are not inherited by Graphify.
    keep = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}
    for key in list(os.environ):
        if key.upper() not in keep:
            del os.environ[key]
    os.environ.update(GRAPHIFY_OUT=str(OUTPUT), GRAPHIFY_QUERY_LOG_DISABLE='1',
                      GRAPHIFY_NO_TIPS='1', GRAPHIFY_NO_CTA='1',
                      USERPROFILE=str(RUNTIME),
                      TEMP=str(RUNTIME), TMP=str(RUNTIME))
    roots = [RUNTIME.resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    def guard(event, args):
        if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
            raise PermissionError('Graphify network and subprocess access is disabled.')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            name = os.fsdecode(args[0])
            if name.startswith('\\\\?\\'):
                name = name[4:]
            path = Path(name).resolve()
            if not any(under(path, allowed) for allowed in roots):
                raise PermissionError(f'Graphify blocked file access: {path}')
    sys.addaudithook(guard)
    os.chdir(CORPUS)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action not in {'refresh', 'query', 'explain', 'path', 'status'}:
        raise RuntimeError('Unsupported action')
    if importlib.metadata.version('graphifyy') != VERSION:
        raise RuntimeError('Unexpected Graphify version; review before upgrading.')
    values = secrets()
    files = snapshot(values)
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    CORPUS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNTIME / 'manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    stale = previous != hashes or not (OUTPUT / 'graph.json').exists()
    if action == 'status':
        print(json.dumps({'version': VERSION, 'files': len(files), 'stale': stale, 'network': 'blocked', 'semantic_extraction': False}))
        return
    if stale or action == 'refresh':
        for path in CORPUS.rglob('*'):
            if path.is_file() and path.relative_to(CORPUS).as_posix() not in files:
                path.unlink()
        for name, raw in files.items():
            target = CORPUS / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != raw:
                target.write_bytes(raw)
    restrict()
    # Direct AST API: no semantic extractors, skill installer, server or HTML exports.
    if stale or action == 'refresh':
        from graphify.extract import extract
        from graphify.build import build_from_json
        import networkx as nx
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = extract([CORPUS / name for name in files], root=CORPUS, cache_root=RUNTIME, parallel=False)
            graph = build_from_json(result, directed=True, root=CORPUS, dedup=False)
        content = json.dumps(nx.node_link_data(graph, edges='links'), ensure_ascii=False)
        check_text(content, values)
        (OUTPUT / 'graph.json').write_text(content, encoding='utf-8')
        manifest_path.write_text(json.dumps(hashes, indent=2), encoding='utf-8')
        print(f'Graph refreshed: {len(files)} source files, {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges. No model calls.')
    check_text((OUTPUT / 'graph.json').read_text(encoding='utf-8'), values)
    if action != 'refresh':
        question = sys.argv[2] if len(sys.argv) > 2 else ''
        if not question:
            raise RuntimeError('A query or symbol is required.')
        check_text(question, values)
        args = ['graphify', action, question]
        if action == 'path':
            args.append(sys.argv[3])
        args.extend(['--graph', str(OUTPUT / 'graph.json')])
        if action == 'query':
            args.extend(['--budget', '1500'])
        sys.argv = args
        from graphify.__main__ import main as graphify_main
        # Scan and bound tool output before it enters the assistant context.
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                graphify_main()
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise RuntimeError('Graph lookup failed. Use targeted source search.') from None
        text = output.getvalue()
        check_text(text, values)
        print(text[:10000])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if isinstance(exc, PermissionError):
            print(str(exc), file=sys.stderr)
        print(f'Graphify stopped: {type(exc).__name__}. Use targeted source search; inspect the local wrapper if needed.', file=sys.stderr)
        sys.exit(1)
