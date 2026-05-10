from pathlib import Path


def test_dockerfile_copies_root_boot_modules():
    dockerfile = Path("Dockerfile").read_text()

    assert "COPY auth_helpers.py ." in dockerfile
    assert "COPY app_migrations.py ." in dockerfile
