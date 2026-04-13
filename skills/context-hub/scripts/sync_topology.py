#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import save_yaml_file
from refresh_context import load_topology_payload, merge_system_exports, merge_system_payload


ENGINEERING_TEAM_IDS = ("engineering",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 1: aggregate engineering exports into topology/system.yaml",
    )
    parser.add_argument(
        "hub",
        nargs="?",
        default=None,
        help="hub root directory, defaults to current working directory",
    )
    parser.add_argument(
        "--hub",
        dest="hub_flag",
        default=None,
        help="hub root directory, same as positional hub",
    )
    return parser.parse_args()


def sync_system_topology(hub_root: Path) -> Path:
    hub_root = Path(hub_root).resolve()
    topology_dir = hub_root / "topology"
    topology_dir.mkdir(parents=True, exist_ok=True)

    system_path = topology_dir / "system.yaml"
    existing_payload = load_topology_payload(system_path, {"services": {}, "infrastructure": {}})
    export_payload = merge_system_exports(hub_root, team_ids=ENGINEERING_TEAM_IDS)
    system_payload = merge_system_payload(existing_payload, export_payload)
    save_yaml_file(system_path, system_payload)
    return system_path


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub_flag or args.hub or ".").resolve()
    try:
        system_path = sync_system_topology(hub_root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Phase 1 export aggregation complete: {system_path}")
    print("GitLab deep scan deferred to a later phase; only engineering exports are aggregated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
