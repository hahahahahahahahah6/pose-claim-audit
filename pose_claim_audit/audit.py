"""Static documentation and provider evidence analysis."""
import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import POSE, NOPOSE


def matches(text, phrases):
    spans = []
    for phrase in sorted(phrases, key=len, reverse=True):
        for match in re.finditer(r'\b' + re.escape(phrase) + r'\b', text):
            if not any(match.start() < b and a < match.end() for a, b in spans):
                spans.append(match.span())
    return spans


def claims(markdown):
    lines = []
    fence = None
    for line in markdown.splitlines():
        mark = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if mark and mark[1][0] == fence[0] and len(mark[1]) >= len(fence) and not mark[2].strip():
                fence = None
            continue
        if mark:
            fence = mark[1]
            lines.append('')
        else:
            lines.append(line)
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        text = paragraph.lower().replace('’', "'").replace("n't", ' not').replace('-', ' ')
        text = ' '.join(text.split())
        spans = matches(text, NOPOSE)
        negative |= bool(spans)
        for a, b in sorted(spans, reverse=True):
            text = text[:a] + ' ' * (b - a) + text[b:]
        positive |= bool(matches(text, POSE))
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    shadowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
    for name in shadowed:
        aliases.pop(name, None)

    def path(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            parent = path(node.value)
            return parent + '.' + node.attr if parent else ''
        return ''

    def construction(node):
        if not isinstance(node, ast.Call):
            return None
        resolved = path(node.func)
        if not resolved.startswith('mediapipe.'):
            return None
        if resolved.endswith('.pose.Pose'):
            return 'pose'
        if resolved.endswith('.PoseLandmarker') or resolved.endswith('.PoseLandmarker.create_from_options'):
            return 'landmarker'
        return None

    bindings = {}

    def key(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = key(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    for node in ast.walk(tree):
        if construction(node):
            return True
        # Bindings also document the supported receiver shapes, independently
        # of the fact that a construction itself already suffices.
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.withitem):
            targets, value = [node.optional_vars], node.context_expr
        kind = construction(value)
        if kind:
            for target in targets:
                bindings[key(target)] = kind
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            kind = construction(node.func.value) or bindings.get(key(node.func.value))
            if kind == 'pose' and node.func.attr == 'process':
                return True
            if kind == 'landmarker' and node.func.attr in ('detect', 'detect_for_video', 'detect_async'):
                return True
    return False


def audit(root, ignores=()):
    root = Path(root)
    if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
        raise ValueError('root must be a readable directory')
    positive = negative = production = test = False
    count = 0
    def ignored(rel):
        return any(fnmatch.fnmatchcase(rel, pattern) for pattern in ignores)
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink()
                         and not ignored((Path(directory) / d).relative_to(root).as_posix()))
        for name in sorted(files):
            file = Path(directory) / name
            rel = file.relative_to(root)
            if file.is_symlink() or ignored(rel.as_posix()):
                continue
            doc = rel.as_posix() == 'README.md' or (file.suffix == '.md' and 'docs' in rel.parts[:-1])
            if not doc and file.suffix != '.py':
                continue
            content = file.read_text(encoding='utf-8')
            count += 1
            if doc:
                p, n = claims(content)
                positive |= p
                negative |= n
            else:
                if any(part in ('fixtures', 'docs', 'examples') for part in rel.parts[:-1]):
                    continue
                is_test = 'tests' in rel.parts[:-1] or name.startswith('test_') or name.endswith('_test.py')
                found = evidence(content)
                if is_test:
                    test |= found
                else:
                    production |= found
    findings = []
    if positive and not production:
        findings.append(dict(rule='documented-pose-claim-false', severity='MEDIUM' if test else 'HIGH', message='Documentation promises body-pose functionality without production evidence.'))
    if negative and production:
        findings.append(dict(rule='documented-no-pose-claim-false', severity='HIGH', message='Documentation denies body-pose functionality but production evidence exists.'))
    return dict(verdict='FAIL' if any(f['severity'] == 'HIGH' for f in findings) else 'PASS', findings=findings, files_scanned=count)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='pose-claim-audit')
    parser.add_argument('root')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['HIGH', 'MEDIUM'], default='HIGH')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, ValueError, UnicodeError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        return 1
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings'])
    result['verdict'] = 'FAIL' if failed else 'PASS'
    if args.json:
        print(json.dumps(result))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {rule}: {message}'.format(**finding))
        if args.verbose:
            print('Files scanned: ' + str(result['files_scanned']))
    return 2 if failed else 0
