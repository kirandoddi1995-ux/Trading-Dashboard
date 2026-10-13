"""Exact reviewed research upload; capture base before copying, no Git writes."""
from overnight_upload_check import main

FILES = (
    'overnight_research_dataset.py',
    'overnight_research_evidence.py',
    'overnight_research_execution.py',
    'overnight_research_ml.py',
    'overnight_research_paper.py',
    'overnight_research_runner.py',
    'overnight_research_trials.py',
    'tests/test_overnight_research_dataset.py',
    'tests/test_overnight_research_evidence.py',
    'tests/test_overnight_research_execution.py',
    'tests/test_overnight_research_ml.py',
    'tests/test_overnight_research_paper.py',
    'tests/test_overnight_research_runner.py',
    'tests/test_overnight_research_trials.py',
    'OVERNIGHT_RESEARCH_2026-10-13.md',
    'overnight_research_upload_check.py',
    'OVERNIGHT_RESEARCH_UPLOAD_2026-10-13.json',
    'requirements-overnight-research.txt',
    '.github/workflows/overnight-research-offline.yml',
)

if __name__ == '__main__':
    raise SystemExit(main('research', FILES))
