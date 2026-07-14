from data_proccessing.cli import _isolation_violations


def test_standalone_package_has_no_legacy_imports() -> None:
    assert _isolation_violations() == []
