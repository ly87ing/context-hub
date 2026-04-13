from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills" / "context-hub"
SCRIPTS_DIR = SKILL_ROOT / "scripts"


def run_script(
    script_name: str,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = SCRIPTS_DIR / script_name
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(cwd or REPO_ROOT),
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )


class ContextHubTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tempdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tempdir.name)
        self.hub_dir = self.workdir / "hub"

    def tearDown(self) -> None:
        self._tempdir.cleanup()
        super().tearDown()
