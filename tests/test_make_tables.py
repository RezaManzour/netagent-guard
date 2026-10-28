"""Smoke test for scripts/make_tables.py: it only reads existing result files and renders markdown."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "make_tables.py")


def run(tmp_path, *extra):
    out = tmp_path / "tables.md"
    subprocess.run([sys.executable, SCRIPT, "--output", str(out), *extra], check=True, cwd=str(tmp_path),
                   capture_output=True, text=True, timeout=120)
    return out.read_text(encoding="utf-8")


def test_offline_tables_match_committed_tables(tmp_path):
    text = run(tmp_path, "--no-v6")
    committed = open(os.path.join(ROOT, "results", "tables.md"), encoding="utf-8").read()
    assert text.strip() == committed.strip()  # regenerated from the CSVs, identical to the checked-in summary
    assert "| combined | 0.69956 | 2.4% [1.1%, 4.0%] | 5.9% [3.8%, 8.3%]" in text


def test_v6_tables_report_recorded_llm_run(tmp_path):
    text = run(tmp_path)
    assert "harmful scenarios: 59 of 1000" in text
    assert "| combined | 0.11176 | 28.8% [17.2%, 40.4%] | 6.6% [4.3%, 9.0%]" in text
    assert "| rule | 0.9 | 32.2% [20.4%, 44.2%] | 2.3% [0.9%, 3.7%]" in text
    assert "openai/gpt-6-luna" in text and "INCOMPLETE" in text
