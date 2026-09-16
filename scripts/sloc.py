from __future__ import annotations

from pathlib import Path

CODE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".dart", ".ex", ".exs", ".fs", ".fsx",
    ".go", ".gql", ".graphql", ".groovy", ".h", ".hpp", ".html", ".java", ".js",
    ".jsx", ".kt", ".kts", ".less", ".lua", ".mjs", ".cjs", ".nim", ".php", ".pl",
    ".pm", ".proto", ".ps1", ".py", ".r", ".rb", ".rs", ".sass", ".scala", ".scss",
    ".sh", ".sql", ".svelte", ".swift", ".toml", ".ts", ".tsx", ".vue", ".yaml",
    ".yml", ".zig"
}
CODE_FILENAMES = {
    "CMakeLists.txt", "Dockerfile", "GNUmakefile", "Justfile", "Makefile", "Rakefile",
    "Taskfile.yml", "Vagrantfile", "go.mod"
}
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".cache", ".next", ".nuxt", ".output", ".parcel-cache",
    ".pytest_cache", ".tox", ".venv", "__pycache__", "bower_components", "build",
    "coverage", "DerivedData", "dist", "generated", "gen", "node_modules", "out", "Pods",
    "target", "third_party", "third-party", "vendor", "venv"
}
IGNORED_FILES = {
    "Cargo.lock", "bun.lock", "bun.lockb", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
    "poetry.lock", "uv.lock", "yarn.lock", "go.sum"
}


def is_code_file(path: Path) -> bool:
    name = path.name
    if name in IGNORED_FILES or name.endswith((".min.js", ".min.css", ".map")):
        return False
    return name in CODE_FILENAMES or path.suffix.lower() in CODE_EXTENSIONS


def count_nonempty_lines(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except (OSError, PermissionError):
        return 0
    if b"\x00" in raw[:8192]:
        return 0
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return 0
    return sum(1 for line in text.splitlines() if line.strip())


def count_tree(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in rel.parts[:-1]):
            continue
        if is_code_file(path):
            total += count_nonempty_lines(path)
    return total
