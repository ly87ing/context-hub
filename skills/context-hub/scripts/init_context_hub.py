#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from _common import (
    build_domains_payload,
    build_identity_md,
    build_llms_text,
    guess_service_type,
    normalize_slug,
    parse_repo_entry,
    parse_test_source_entry,
    save_yaml_file,
)
from runtime.capability_ops import build_initial_ownership_payload
from runtime.hub_io import safe_write_text


SCRIPT_FILES_TO_COPY = (
    "_common.py",
    "yaml_compat.py",
    "create_capability.py",
    "refresh_context.py",
    "sync_capability_status.py",
    "bootstrap_credentials_check.py",
    "update_llms_txt.py",
    "sync_topology.py",
    "check_consistency.py",
    "check_stale.py",
)
TEMPLATE_FILES_TO_COPY = (
    "spec.md",
    "design.md",
    "architecture.md",
    "testing.md",
)
TEAM_EXPORTS = ("product", "design", "engineering", "qa")


def ensure_output_ready(output_dir: Path, force: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise ValueError(f"output directory is not empty: {output_dir}. use --force to continue")


def build_system_yaml_payload(repos: list[dict[str, str]]) -> dict:
    services = {}
    for repo in repos:
        services[repo["name"]] = {
            "domain": repo["domain"],
            "type": guess_service_type(repo["name"], repo["url"]),
            "repo": repo["url"],
            "default_branch": "main",
            "owner": repo["owner"],
            "lang": "unknown",
            "framework": "unknown",
            "depends_on": [],
            "provides": [],
        }
    return {"services": services, "infrastructure": {}}


def build_testing_sources_payload(test_sources: list[dict[str, str]]) -> dict:
    return {"sources": test_sources}


def report_action(dry_run: bool, message: str) -> None:
    if dry_run:
        print(f"DRY-RUN {message}")


def ensure_directory(path: Path, dry_run: bool) -> None:
    report_action(dry_run, f"mkdir {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def write_text_file(path: Path, content: str, dry_run: bool) -> None:
    report_action(dry_run, f"write {path}")
    if not dry_run:
        safe_write_text(path, content)


def write_yaml_file(path: Path, payload: dict, dry_run: bool) -> None:
    report_action(dry_run, f"write {path}")
    if not dry_run:
        save_yaml_file(path, payload)


def copy_file(src: Path, dst: Path, dry_run: bool) -> None:
    report_action(dry_run, f"copy {src} -> {dst}")
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, dry_run: bool) -> None:
    report_action(dry_run, f"copytree {src} -> {dst}")
    if not dry_run:
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )


def write_decision_files(output_dir: Path, dry_run: bool) -> None:
    decisions_dir = output_dir / "decisions"
    ensure_directory(decisions_dir, dry_run)
    write_text_file(
        decisions_dir / "_index.md",
        "\n".join(
            [
                "# Architecture Decisions",
                "",
                "| # | Title | Status | Date | Capability |",
                "|:--|:--|:--|:--|:--|",
                "",
            ]
        ),
        dry_run,
    )


def write_gitignore(output_dir: Path, dry_run: bool) -> None:
    write_text_file(
        output_dir / ".gitignore",
        "\n".join(
            [
                "__pycache__/",
                "*.pyc",
                ".DS_Store",
                "",
            ]
        ),
        dry_run,
    )


def copy_templates(skill_root: Path, output_dir: Path, dry_run: bool) -> None:
    target_dir = output_dir / "capabilities" / "_templates"
    ensure_directory(target_dir, dry_run)
    for filename in TEMPLATE_FILES_TO_COPY:
        copy_file(skill_root / "templates" / filename, target_dir / filename, dry_run)
    copy_tree(skill_root / "templates", output_dir / "templates", dry_run)
    copy_file(
        skill_root / "templates" / "decision.md",
        output_dir / "decisions" / "_template.md",
        dry_run,
    )
    copy_file(
        skill_root / "templates" / "gitlab-ci.yml",
        output_dir / ".gitlab-ci.yml",
        dry_run,
    )


def copy_runtime_scripts(skill_root: Path, output_dir: Path, dry_run: bool) -> None:
    target_dir = output_dir / "scripts"
    ensure_directory(target_dir, dry_run)
    for filename in SCRIPT_FILES_TO_COPY:
        copy_file(skill_root / "scripts" / filename, target_dir / filename, dry_run)
    copy_tree(skill_root / "scripts" / "runtime", target_dir / "runtime", dry_run)
    copy_tree(skill_root / "scripts" / "integrations", target_dir / "integrations", dry_run)


def create_team_exports(output_dir: Path, dry_run: bool) -> None:
    for team_id in TEAM_EXPORTS:
        ensure_directory(output_dir / "teams" / team_id / "exports", dry_run)


def target_hub_is_git_repo(target_hub: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(target_hub),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def maybe_handle_git_flags(target_hub: Path, auto_commit: bool, auto_push: bool, dry_run: bool) -> None:
    if not auto_commit and not auto_push:
        return
    if dry_run:
        if auto_commit:
            print(f"DRY-RUN target hub auto-commit requested: {target_hub}")
        if auto_push:
            print(f"DRY-RUN target hub auto-push requested: {target_hub}")
        return
    if not target_hub_is_git_repo(target_hub):
        print(f"INFO auto git skipped: target hub is not a git repo: {target_hub}")
        return
    if auto_commit:
        print(f"INFO target hub is a git repo, auto-commit requested but skipped: {target_hub}")
    if auto_push:
        print(f"INFO target hub is a git repo, auto-push requested but skipped: {target_hub}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="initialize a new context-hub project directory")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--name", required=True, help="project name")
    parser.add_argument("--id", required=True, help="project slug")
    parser.add_argument("--summary", default="global project context entrypoint", help="project summary")
    parser.add_argument("--gitlab", default="", help="gitlab group or project url")
    parser.add_argument("--ones", default="", help="ones project url")
    parser.add_argument("--figma", default="", help="figma team url")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="repo entry in name|url|domain|owner format; domain and owner are optional",
    )
    parser.add_argument(
        "--test-source",
        action="append",
        default=[],
        help="test source entry in name|url|type format; type is optional",
    )
    parser.add_argument("--force", action="store_true", help="allow generating into a non-empty directory")
    parser.add_argument("--dry-run", action="store_true", help="report planned actions without writing files")
    parser.add_argument("--auto-commit", action="store_true", help="reserved flag for future git automation")
    parser.add_argument("--auto-push", action="store_true", help="reserved flag for future git automation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_root = Path(__file__).resolve().parent.parent
    output_dir = Path(args.output).resolve()
    ensure_output_ready(output_dir, args.force)

    project_id = normalize_slug(args.id)
    repos = [parse_repo_entry(entry) for entry in args.repo]
    test_sources = [parse_test_source_entry(entry) for entry in args.test_source]

    identity_text = build_identity_md(
        project_name=args.name,
        summary=args.summary,
        repos=repos,
        gitlab_url=args.gitlab,
        ones_url=args.ones,
        figma_url=args.figma,
    )
    domains_payload = build_domains_payload(repos)
    system_payload = build_system_yaml_payload(repos)
    testing_payload = build_testing_sources_payload(test_sources)
    ownership_payload = build_initial_ownership_payload(project_id, args.name)

    ensure_directory(output_dir, args.dry_run)
    write_text_file(output_dir / "IDENTITY.md", identity_text, args.dry_run)
    write_yaml_file(output_dir / "topology" / "domains.yaml", domains_payload, args.dry_run)
    write_yaml_file(output_dir / "topology" / "system.yaml", system_payload, args.dry_run)
    write_yaml_file(output_dir / "topology" / "testing-sources.yaml", testing_payload, args.dry_run)
    write_yaml_file(output_dir / "topology" / "ownership.yaml", ownership_payload, args.dry_run)

    write_decision_files(output_dir, args.dry_run)
    write_gitignore(output_dir, args.dry_run)
    copy_templates(skill_root, output_dir, args.dry_run)
    copy_runtime_scripts(skill_root, output_dir, args.dry_run)
    create_team_exports(output_dir, args.dry_run)

    llms_text = build_llms_text(
        project_name=args.name,
        summary=args.summary,
        domains_payload=domains_payload,
        system_payload=system_payload,
        testing_sources_payload=testing_payload,
    )
    ensure_directory(output_dir / ".context", args.dry_run)
    write_text_file(output_dir / ".context" / "llms.txt", llms_text, args.dry_run)

    maybe_handle_git_flags(output_dir, args.auto_commit, args.auto_push, args.dry_run)

    if args.dry_run:
        print(f"DRY-RUN initialization complete for {args.name} ({project_id})")
        return 0

    print(f"initialized context-hub: {args.name} ({project_id})")
    print(f"output directory: {output_dir}")
    print(f"repositories: {len(repos)}")
    print(f"test sources: {len(test_sources)}")
    print("next steps:")
    print("  1. run python scripts/check_consistency.py")
    print("  2. run python scripts/create_capability.py --name <capability> --domain <domain>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
