"""Check the two invariants that cannot be left to review.

SAFETY_CLASS: not applicable (build tooling, not device software)

Run locally with:

    uv run python tools/check_invariants.py

1. Dependency direction. `mri_services -> mri_core -> mri_contract`, never
   reversed, and neither of the lower two may import Flask. This is what lets
   transport be classified below the compute core; an import that crosses the
   boundary silently invalidates that argument.

2. Safety classification. Every module under `src/` declares a `SAFETY_CLASS`
   that matches the manifest in DESIGN.md. Without this the constant and the
   manifest disagree within a month and the manifest becomes fiction -- which
   already happened once during development, when `schema.py` carried its class
   in the docstring and not as a constant.

Imports are read with `ast` rather than grep so that a mention in a comment or a
docstring is not a false positive.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
MANIFEST = ROOT / "DESIGN.md"

# package -> module prefixes it must never import
FORBIDDEN = {
    "mri_contract": ("flask", "werkzeug", "PIL", "mri_core", "mri_services"),
    "mri_core": ("flask", "werkzeug", "mri_services"),
}


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by a file, including relative imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def declared_safety_class(path: Path) -> str | None:
    """Value of the module-level `SAFETY_CLASS = "..."` assignment, if present."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "SAFETY_CLASS":
                if isinstance(node.value, ast.Constant):
                    return str(node.value.value)
    return None


def manifest_classes() -> dict[str, str]:
    """Parse the `| Module | Class |` table out of DESIGN.md.

    Returns glob pattern -> class letter. Patterns are matched against paths
    relative to the repository root.
    """
    rows: dict[str, str] = {}
    in_table = False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\|\s*Module\s*\|\s*Class\s*\|", line):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            if set(line) <= set("|- "):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            patterns = re.findall(r"`([^`]+)`", cells[0])
            klass = cells[1].split()[0]
            for pattern in patterns:
                rows[pattern] = klass
    return rows


def check_dependency_direction() -> list[str]:
    failures = []
    for package, forbidden in FORBIDDEN.items():
        for path in sorted((SRC / package).rglob("*.py")):
            offenders = imported_modules(path) & set(forbidden)
            for offender in sorted(offenders):
                failures.append(
                    f"{path.relative_to(ROOT)} imports {offender!r}; "
                    f"{package} may not depend on it"
                )
    return failures


def check_safety_classes() -> list[str]:
    expected = manifest_classes()
    if not expected:
        return ["could not parse the safety classification table in DESIGN.md"]

    failures = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "__init__.py":
            continue  # no logic, exempt by the manifest
        relative = path.relative_to(ROOT / "src").as_posix()

        matches = [k for pattern, k in expected.items() if fnmatch.fnmatch(relative, pattern)]
        if not matches:
            failures.append(f"{relative} is not covered by the DESIGN.md manifest")
            continue

        declared = declared_safety_class(path)
        if declared is None:
            failures.append(f"{relative} declares no SAFETY_CLASS")
        elif declared != matches[0]:
            failures.append(
                f"{relative} declares SAFETY_CLASS={declared!r}, "
                f"manifest says {matches[0]!r}"
            )
    return failures


def main() -> int:
    checks = [
        ("dependency direction", check_dependency_direction),
        ("safety classification", check_safety_classes),
    ]
    failed = False
    for name, check in checks:
        failures = check()
        if failures:
            failed = True
            print(f"FAIL  {name}")
            for failure in failures:
                print(f"      {failure}")
        else:
            print(f"ok    {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
