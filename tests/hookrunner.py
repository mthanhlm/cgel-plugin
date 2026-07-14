"""Subprocess runners for CGEL hook scripts and the cgel CLI.

Hooks are exercised exactly as Claude Code runs them: JSON payload on stdin,
assertions on exit code / stdout / stderr. Never import hook scripts as
modules.
"""

import json
import os
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PLUGIN_ROOT, "scripts")
CLI = os.path.join(PLUGIN_ROOT, "bin", "cgel")


def run_hook(script_name, payload, env=None, raw_stdin=None):
    merged_env = os.environ.copy()
    merged_env.update(env or {})
    stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, script_name)],
        input=stdin,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cli(args, cwd, env=None):
    merged_env = os.environ.copy()
    merged_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, CLI] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def decision_line(stdout):
    lines = [line for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""
