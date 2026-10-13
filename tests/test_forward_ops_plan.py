"""Disabled XML plans, date pins, quoting, noncatchup and separate namespaces."""
from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from forward_ops_plan import plans

ARGS = {'sid': 'S-1-5-21-1234', 'code': r'C:\Private Code\capture',
        'python': r'C:\Private Code\capture\.venv\Scripts\python.exe',
        'state': r'C:\Private State\Forward', 'ops': r'C:\Private State\Operations'}


def test_disabled_date_pinned_and_versioned_audit() -> None:
    result = plans(date(2026, 10, 14), **ARGS)
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert len(result) == 3
    for name, xml in result.items():
        root = ET.fromstring(xml)
        assert root.findtext('t:Settings/t:Enabled', namespaces=ns) == 'false'
        assert root.findtext('t:Settings/t:StartWhenAvailable', namespaces=ns) == 'false'
        assert root.findtext('t:Principals/t:Principal/t:RunLevel', namespaces=ns) == 'LeastPrivilege'
        args = root.findtext('t:Actions/t:Exec/t:Arguments', namespaces=ns) or ''
        assert '2026-10-14' in args and 'forward_ops_task.ps1' in args
        assert '-WindowStyle Hidden' in args and '-AuditTask' in args
        assert '<?xml' not in xml
        if name.endswith('audit'):
            assert '-Mode audit' in args and '15:40:00+05:30' in xml
        if name.endswith('poll'):
            assert 'PT6H1M' in xml and '09:30:30+05:30' in xml and '15:32:30+05:30' in xml
            assert [n.tag.split('}')[-1] for n in root.find('t:Triggers/t:TimeTrigger', ns)] == ['Repetition','StartBoundary','EndBoundary','Enabled']  # type: ignore[union-attr]


@pytest.mark.parametrize('change', [{'sid':'bad'}, {'python': r'C:\other\python.exe'},
    {'ops': ARGS['state']}, {'state': ARGS['code']}, {'ops': r'C:\a\..\ops'},
    {'code': 'relative'}, {'ops': 'C:\bad"path'}, {'ops': 'C:\bad\npath'}])
def test_unsafe_plan(change: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        plans(date(2026, 10, 14), **{**ARGS, **change})


def test_launcher_no_time_or_task_mutation() -> None:
    text = (Path(__file__).resolve().parents[1] / 'forward_ops_task.ps1').read_text()
    assert '-WindowStyle Hidden -Wait -PassThru' in text
    for forbidden in ('Register-ScheduledTask', 'Enable-ScheduledTask', 'w32tm', 'Set-Service', 'Remove-Item'):
        assert forbidden not in text


@pytest.mark.parametrize('day', [date(2026,10,20), date(2026,10,18), date(2026,11,8), date(2027,1,4)])
def test_nonregular_and_unknown_year(day: date) -> None:
    with pytest.raises(ValueError):
        plans(day, **ARGS)
