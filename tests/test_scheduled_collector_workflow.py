"""Dispatch-only collector must not advertise unreachable GitHub cron paths."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_collector_has_only_reachable_dispatch_collection():
    workflow = (ROOT / '.github/workflows/scheduled-collector.yml').read_text()
    assert '  workflow_dispatch:' in workflow
    assert '  schedule:' not in workflow
    assert 'github.event.schedule' not in workflow
    assert "github.event_name == 'schedule'" not in workflow
    assert 'options: [scan, global, open, close, weekly, all]' in workflow
    assert workflow.count('run: python scheduled_collector.py --mode') == 1
    assert 'run: python scheduled_collector.py --mode "${{ inputs.mode }}"' in workflow
    assert workflow.index('--check') < workflow.index('--mode')
    assert "github.event_name == 'workflow_dispatch' && inputs.apply_migrations" in workflow


def test_external_dispatcher_still_targets_collector_workflow():
    source = (ROOT / 'supabase/functions/dispatch-scheduled-collector/index.ts').read_text()
    assert '"scheduled-collector.yml"' in source
    assert 'mode: payload.mode' in source
