#!/usr/bin/env python3
"""
Team Scaffolding Tool for Agentic Football.

Creates a new AI soccer team by cloning and customizing a base team template.

Usage:
    python scaffold_team.py ai-team-strands-<name> [--base <base_team>] [--force]
    python scaffold_team.py <name> [--base <base_team>] [--force]

Examples:
    python scaffold_team.py ai-team-strands-possession --base diamond
    python scaffold_team.py counter-attack --base balanced
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
DEFAULT_BASE = "diamond"
POSITIONS = ["ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2"]
POS_NAMES = ["gk", "def", "mid", "fwd1", "fwd2"]


def clean_team_name(name_input: str) -> tuple[str, str]:
    """Return (full_dir_name, short_slug) from input.
    e.g. 'wings' -> ('ai-team-strands-wings', 'wings')
         'ai-team-strands-wings' -> ('ai-team-strands-wings', 'wings')
    """
    raw = name_input.strip().strip("/\\")
    if raw.startswith("ai-team-strands-"):
        short = raw[len("ai-team-strands-"):]
        full = raw
    else:
        short = raw
        full = f"ai-team-strands-{raw}"

    # Normalize short to valid identifier slug
    short_slug = re.sub(r"[^a-zA-Z0-9_]", "_", short).lower()
    return full, short_slug


def to_pascal_case(snake_str: str) -> str:
    """Convert snake_case or kebab-case to PascalCase."""
    words = re.split(r"[-_]", snake_str)
    return "".join(w.capitalize() for w in words if w)


def rmtree(path: Path):
    """Safely remove directory tree handling read-only permissions."""
    def _onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path.exists():
        shutil.rmtree(path, onerror=_onerror)


def copy_tree_filtered(src: Path, dst: Path):
    """Copy directory structure excluding caches, venvs, and build outputs."""
    ignore_patterns = shutil.ignore_patterns(
        ".venv",
        "uv.lock",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "cdk.out",
        "node_modules",
        ".bedrock_agentcore.yaml",
        ".DS_Store",
        "dist",
        "build",
        "*.egg-info",
    )
    shutil.copytree(src, dst, ignore=ignore_patterns)


def scaffold_team(target_name: str, base_team: str = DEFAULT_BASE, force: bool = False) -> Path:
    """Scaffold a new agentic football team."""
    full_dir_name, short_slug = clean_team_name(target_name)
    target_dir = REPO_ROOT / full_dir_name

    # Resolve base directory
    base_full, base_slug = clean_team_name(base_team)
    base_dir = REPO_ROOT / base_full

    if not base_dir.is_dir():
        # Try finding partial match
        matching = [d for d in REPO_ROOT.iterdir() if d.is_dir() and d.name.startswith("ai-team-") and base_team in d.name]
        if matching:
            base_dir = matching[0]
            base_full = base_dir.name
            base_slug = base_full.replace("ai-team-strands-", "").replace("-", "_")
        else:
            raise FileNotFoundError(f"Base team directory '{base_full}' not found in {REPO_ROOT}")

    if target_dir.exists():
        if force:
            print(f"  Overwriting existing directory: {target_dir.name}")
            rmtree(target_dir)
        else:
            raise FileExistsError(f"Target team directory '{target_dir.name}' already exists. Use --force to overwrite.")

    print(f"Scaffolding new team:")
    print(f"  Target: {full_dir_name}")
    print(f"  Base:   {base_dir.name}")
    print(f"  Slug:   {short_slug}")
    print()

    # 1. Copy base tree
    copy_tree_filtered(base_dir, target_dir)

    # 2. Update agentcore/agentcore.json
    agentcore_json_path = target_dir / "agentcore" / "agentcore.json"
    if agentcore_json_path.exists():
        data = json.loads(agentcore_json_path.read_text(encoding="utf-8"))
        pascal_project = f"TeamStrands{to_pascal_case(short_slug)}"
        data["name"] = pascal_project
        if "tags" in data and isinstance(data["tags"], dict):
            data["tags"]["agentcore:project-name"] = pascal_project

        for runtime in data.get("runtimes", []):
            code_loc = runtime.get("codeLocation", "")
            # e.g. "ai-gk/" -> "gk"
            pos = code_loc.strip("/").replace("ai-", "")
            runtime["name"] = f"ai_{short_slug}_{pos}_agent"

        agentcore_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"  ✓ Updated {agentcore_json_path.relative_to(REPO_ROOT)}")

    # 3. Update each position's .bedrock_agentcore.yaml.template and pyproject.toml
    for pos in POSITIONS:
        pos_dir = target_dir / pos
        if not pos_dir.is_dir():
            continue

        pos_slug = pos.replace("ai-", "")
        agent_name = f"ai_{short_slug}_{pos_slug}_agent"

        # Template YAML
        template_file = pos_dir / ".bedrock_agentcore.yaml.template"
        if template_file.exists():
            content = template_file.read_text(encoding="utf-8")
            # Replace old agent names
            content = re.sub(r"ai_[a-zA-Z0-9_-]+_(gk|def|mid|fwd1|fwd2)_agent", agent_name, content)
            template_file.write_text(content, encoding="utf-8")
            print(f"  ✓ Updated {template_file.relative_to(REPO_ROOT)}")

        # pyproject.toml
        pyproject = pos_dir / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text(encoding="utf-8")
            content = re.sub(r'name = "[^"]+"', f'name = "{agent_name}"', content)
            pyproject.write_text(content, encoding="utf-8")

    # 4. Update README.md in target directory
    readme_path = target_dir / "README.md"
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        title_line = f"# AI Team ({to_pascal_case(short_slug)})"
        lines = content.splitlines()
        if lines:
            lines[0] = title_line
        readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  ✓ Updated {readme_path.relative_to(REPO_ROOT)}")

    # 5. Ensure scripts are executable
    for script_name in ["deploy-all.sh", "deploy_all.py"]:
        script_path = target_dir / script_name
        if script_path.exists():
            st = os.stat(script_path)
            os.chmod(script_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"\n🎉 Successfully created team: {full_dir_name}")
    return target_dir


def main():
    parser = argparse.ArgumentParser(
        description="Scaffold a new agentic football team from a base template",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "name",
        help="Name of new team (e.g. 'ai-team-strands-possession' or 'possession')",
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help="Base team template to clone (default: 'diamond')",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite target directory if it already exists",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip running local tests on the new team after creation",
    )

    args = parser.parse_args()

    try:
        new_dir = scaffold_team(args.name, base_team=args.base, force=args.force)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not args.skip_verify:
        print("\nVerifying new team with test runner...")
        res = subprocess.run(
            [sys.executable, str(REPO_ROOT / "run_tests.py"), new_dir.name],
            cwd=REPO_ROOT,
        )
        if res.returncode != 0:
            print(f"\n⚠️ Verification tests failed for new team {new_dir.name}.")
            sys.exit(1)
        else:
            print(f"✅ All local tests pass for {new_dir.name}.")


if __name__ == "__main__":
    main()
