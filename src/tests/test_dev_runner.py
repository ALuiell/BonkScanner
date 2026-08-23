from __future__ import annotations

from tools.dev_runner import changed_paths, scan_watch_files


def test_dev_runner_watches_python_and_qss_only(tmp_path) -> None:
    source = tmp_path / "src"
    styles = tmp_path / "ui_assets"
    cache = source / "__pycache__"
    source.mkdir()
    styles.mkdir()
    cache.mkdir()

    python_file = source / "feature.py"
    qss_file = styles / "theme.qss"
    python_file.write_text("value = 1\n", encoding="utf-8")
    qss_file.write_text("QWidget {}\n", encoding="utf-8")
    (source / "notes.txt").write_text("ignored\n", encoding="utf-8")
    (cache / "feature.py").write_text("ignored\n", encoding="utf-8")

    snapshot = scan_watch_files(tmp_path)

    assert set(snapshot) == {python_file, qss_file}


def test_dev_runner_detects_add_modify_and_remove(tmp_path) -> None:
    source = tmp_path / "src"
    styles = tmp_path / "ui_assets"
    source.mkdir()
    styles.mkdir()
    existing = source / "existing.py"
    removed = styles / "removed.qss"
    existing.write_text("before\n", encoding="utf-8")
    removed.write_text("before\n", encoding="utf-8")
    before = scan_watch_files(tmp_path)

    existing.write_text("after with another size\n", encoding="utf-8")
    removed.unlink()
    added = source / "added.py"
    added.write_text("new\n", encoding="utf-8")
    after = scan_watch_files(tmp_path)

    assert set(changed_paths(before, after)) == {existing, removed, added}
