"""No Git/hosted writes; exact package identity and redacted CLI failure."""
from pathlib import Path
import pytest
import versioned_capture_upload_check as check


def test_exact_package_and_no_private_extras() -> None:
    root = Path(__file__).resolve().parents[1]
    check.validate(root, set(check.FILES))
    with pytest.raises(ValueError):
        check.validate(root, set(check.FILES) | {'client_secret.json'})


def test_missing_manifest_and_invalid_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError):
        check.validate(tmp_path, set())
    assert check.main(['--root', str(tmp_path), '--base', 'not-a-sha']) == 2
    assert 'BLOCKED' in capsys.readouterr().out
