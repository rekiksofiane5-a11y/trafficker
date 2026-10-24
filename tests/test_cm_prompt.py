"""Assistant « Prompt CM360 » (JavaScript) : vérifications Node."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.skipif(not shutil.which("node"), reason="Node absent")
def test_cm_prompt_rules():
    r = subprocess.run(["node", os.path.join(ROOT, "tests", "cm_prompt_check.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="Node absent")
def test_pivot_rules():
    r = subprocess.run(["node", os.path.join(ROOT, "tests", "pivot_check.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="Node absent")
def test_quality_checks_and_monitoring_rules():
    r = subprocess.run(["node", os.path.join(ROOT, "tests", "quality.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
