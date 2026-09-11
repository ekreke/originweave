"""Fallback logical line counter used by ``make cloc`` when tokei/cloc are absent.

Prints code / comment / blank counts for the given paths. Python files are
counted with :mod:`tokenize`; other files fall back to a line-prefix heuristic.
"""

from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

SKIP_DIRS = {"tests", "fixtures", "generated", "vendor", "__pycache__"}


def _python_counts(path: Path) -> tuple[int, int, int]:
    source = path.read_text(encoding="utf-8", errors="replace")
    blank = sum(1 for line in source.splitlines() if not line.strip())
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comment_lines.add(token.start[0])
            elif token.type not in {
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENDMARKER,
            }:
                code_lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    comment_only = comment_lines - code_lines
    code = len(code_lines)
    return code, len(comment_only), blank


def _text_counts(path: Path) -> tuple[int, int, int]:
    code = comment = blank = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif stripped.startswith(("#", "//")) or stripped.startswith("/*"):
            comment += 1
        else:
            code += 1
    return code, comment, blank


def _iter_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts):
                continue
            files.append(path)
    return files


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv] or [Path("src/originweave")]
    code = comment = blank = 0
    counted: list[tuple[str, int, int, int]] = []
    for path in _iter_files(roots):
        if path.suffix == ".py":
            c, m, b = _python_counts(path)
        else:
            c, m, b = _text_counts(path)
        code += c
        comment += m
        blank += b
        counted.append((str(path), c, m, b))

    for name, c, m, b in counted:
        print(f"{name}: code={c} comment={m} blank={b}")
    print("-" * 52)
    print(f"files={len(counted)} code={code} comment={comment} blank={blank}")
    print(f"code+comment+blank={code + comment + blank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
