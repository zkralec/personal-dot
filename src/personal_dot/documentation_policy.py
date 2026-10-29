"""Deterministic preview policy. Review approval cannot waive these checks."""

import difflib
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from personal_dot.config import Settings, get_settings
from personal_dot.documentation_schemas import EditorOutput
from personal_dot.repository_inspection import SECRET_CONTENT, SECRET_NAMES, SKIP_DIRS, safe_path

POLICY_VERSION = 'documentation-preview-v1'
POLICY_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PROTECTED = re.compile(r'(?i)(?:agent|instruction|security|auth|permission|polic|deploy|operat|config|install|setup|workflow|dependenc|requirement|credential|secret|approval)')
EXECUTABLE = re.compile(r'(?i)<(?:script|iframe|object)\b|\{%|\{\{|```\s*(?:\{(?:python|r|exec|bash|julia)|dataviewjs|(?:python|bash|js)\s+exec)|jupyter-execute')
# Initial policy permits explanatory insertions only, with no new instructions,
# commands, links, headings, configuration, maturity or successful-check claims.
FORBIDDEN_ADDITION = re.compile(
    r'(?im)^\s*(?:#|>|```|~~~|\t| {4})|[<>$]|\]\(|://|'
    r'\b(?:curl|docker|sudo|chmod|pip|npm|uv|git)\s|\bpython\s+-|'
    r'^\s*(?:run|execute|install|invoke)\b|'
    r'\b(?:production.ready|deployed|verified|passed|successful|guaranteed|authoriz[a-z]*|permissions?|polic(?:y|ies)|approv[a-z]*|security|credentials?|secrets?)\b|'
    r'\b[A-Z][A-Z_]{3,}\s*='
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def policy_configuration(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {'version': POLICY_VERSION, 'implementation_sha256': POLICY_SHA256, 'max_files': s.docs_preview_max_files,
            'max_changed_lines': s.docs_preview_max_changed_lines,
            'file_bytes': 65_536, 'evidence_bytes': 32_768, 'evidence_lines': 200,
            'public_snapshots_only': True, 'edits': 'insertions_only'}


def eligible_path(path: str, *, target: bool) -> bool:
    if not safe_path(path) or any(SECRET_NAMES.fullmatch(p) for p in path.split('/')):
        return False
    if any(p.lower() in SKIP_DIRS or p.startswith('.') for p in path.split('/')):
        return False
    if PROTECTED.search(path) or path.lower() in {'docs/documentation-maintenance.md', 'docs/status.md'}:
        return False
    if target:
        return path == 'README.md' or path.startswith('docs/') and path.endswith('.md')
    return path.endswith(('.md', '.py', '.js', '.ts', '.go', '.rs'))


def screened(text: str) -> bool:
    return not (SECRET_CONTENT.search(text) or any((ord(c) < 32 or unicodedata.category(c) in {'Cf', 'Cs'}) and c not in '\n\t' for c in text))


def protected_anchor(text: str, after_line: int) -> bool:
    headings: list[tuple[int, str]] = []
    fence = ''
    lines = text.splitlines()
    for index, line in enumerate(lines[:after_line], 1):
        match = re.match(r'^\s*(?:(?:[-*+]|[0-9]+[.])\s+)?(`{3,}|~{3,})', line)
        if match:
            marker = match[1][0]
            fence = '' if fence == marker else marker
            if index == after_line:
                return True
        if fence:
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading:
            level = len(heading[1])
            headings = [(n, h) for n, h in headings if n < level]
            headings.append((level, heading[2]))
    anchor = lines[after_line - 1]
    return bool(fence or PROTECTED.search(' '.join(h for _, h in headings))
                or anchor.startswith(('    ', '\t', '>')))


def validate_candidate(editor: EditorOutput, prepared: dict[str, Any]) -> dict[str, Any]:
    context = prepared['context']
    targets = {f['path']: f for f in context['targets']}
    evidence = {f['source_id']: f['text'] for f in context['evidence']}
    codes: set[str] = set()
    if any(ref not in evidence for ref in editor.evidence_refs):
        codes.add('invalid_evidence_reference')
    if editor.outcome != 'candidate':
        if editor.edits:
            codes.add('edits_with_no_candidate')
        return {'passed': not codes, 'codes': sorted(codes), 'diff': '', 'changed_lines': 0, 'changed_files': 0}
    if not editor.edits:
        codes.add('no_op')
    changed = {edit.path for edit in editor.edits}
    if len(changed) > prepared['policy']['max_files']:
        codes.add('file_count_limit')
    changed_lines = sum(len(edit.text.splitlines()) for edit in editor.edits)
    if changed_lines > prepared['policy']['max_changed_lines']:
        codes.add('changed_line_limit')
    anchors: set[tuple[str, int]] = set()
    for edit in editor.edits:
        if edit.path not in targets or not eligible_path(edit.path, target=True):
            codes.add('forbidden_path')
            continue
        original = targets[edit.path]['text']
        if (edit.path, edit.after_line) in anchors:
            codes.add('duplicate_anchor')
        anchors.add((edit.path, edit.after_line))
        if edit.after_line > len(original.splitlines()) or not original.endswith('\n'):
            codes.add('invalid_anchor')
        elif protected_anchor(original, edit.after_line):
            codes.add('protected_section_or_code')
        if not edit.text.strip() or not edit.text.endswith('\n') or edit.text.strip() in original:
            codes.add('no_op')
        if FORBIDDEN_ADDITION.search(unicodedata.normalize("NFKC", edit.text)) or EXECUTABLE.search(edit.text):
            codes.add('unsupported_markup_command_or_claim')
        if not screened(edit.text):
            codes.add('sensitive_content')
        for support in edit.support:
            if support.source_id not in evidence or support.source_id not in editor.evidence_refs:
                codes.add('invalid_evidence_reference')
            elif support.quote not in evidence[support.source_id]:
                codes.add('invalid_support_quote')
    if codes:
        return {'passed': False, 'codes': sorted(codes), 'diff': '',
                'changed_lines': changed_lines, 'changed_files': len(changed)}
    diffs = []
    for path in sorted(changed):
        original = targets[path]['text']
        lines = original.splitlines(keepends=True)
        for edit in sorted((e for e in editor.edits if e.path == path), key=lambda e: e.after_line, reverse=True):
            lines.insert(edit.after_line, edit.text)
        updated = ''.join(lines)
        if len(updated.encode()) > prepared['policy']['file_bytes']:
            codes.add('file_size_limit')
        diffs.extend(difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True),
                                        fromfile='a/' + path, tofile='b/' + path))
    return {'passed': not codes, 'codes': sorted(codes), 'diff': ''.join(diffs),
            'changed_lines': changed_lines, 'changed_files': len(changed)}
