#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json

from integrations.gitlab_adapter import preflight_gitlab
from integrations.ones_adapter import preflight_ones


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="check shared credential availability for context-hub integrations"
    )
    parser.add_argument(
        "--gitlab-url",
        default="",
        help="optional GitLab URL used to resolve the instance; defaults to gitlab",
    )
    parser.add_argument(
        "--check-ones",
        action="store_true",
        help="include ONES credential preflight",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload: dict[str, object] = {
        "gitlab": preflight_gitlab(args.gitlab_url or None),
    }
    if args.check_ones:
        payload["ones"] = preflight_ones()

    print(json.dumps(payload, sort_keys=True))

    all_ok = all(
        isinstance(result, dict) and bool(result.get("ok"))
        for result in payload.values()
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
