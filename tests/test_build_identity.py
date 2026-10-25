from build_identity import source_identity


def test_missing_metadata_never_guesses_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    (tmp_path / "app.py").write_text("# synthetic", encoding="ascii")
    report = source_identity(tmp_path)
    assert report["commit"] == "UNKNOWN"
    assert len(report["app_sha256"]) == 64
    assert report["integrity"] == "NOT_ATTESTED"


def test_loose_and_packed_head_are_public_metadata_only(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (git / "refs" / "heads" / "main").write_text("a" * 40, encoding="ascii")
    assert source_identity(tmp_path)["commit"] == "a" * 40
    (git / "HEAD").write_text("ref: refs/heads/release\n", encoding="ascii")
    (git / "packed-refs").write_text("b" * 40 + " refs/heads/release\n", encoding="ascii")
    assert source_identity(tmp_path)["commit"] == "b" * 40


def test_untrusted_reference_is_not_followed(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: ../private\n", encoding="ascii")
    assert source_identity(tmp_path)["commit"] == "UNKNOWN"


def test_detached_head_and_gitfile_are_explicit(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("c" * 40, encoding="ascii")
    assert source_identity(tmp_path)["commit"] == "c" * 40
    (git / "HEAD").write_text("invalid", encoding="ascii")
    assert source_identity(tmp_path)["commit"] == "UNKNOWN"
