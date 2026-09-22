import pytest

from app.core import paths
from app.services.ingestion.storage import LocalStorage

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
class TestLocalStorage:
    async def test_put_then_get_roundtrip(self, tmp_path):
        storage = LocalStorage(root=tmp_path)
        await storage.put("applications/abc/file.png", b"hello", "image/png")
        assert await storage.exists("applications/abc/file.png") is True
        assert await storage.get("applications/abc/file.png") == b"hello"

    async def test_missing_key_does_not_exist(self, tmp_path):
        storage = LocalStorage(root=tmp_path)
        assert await storage.exists("nope") is False

    async def test_path_traversal_key_rejected(self, tmp_path):
        storage = LocalStorage(root=tmp_path)
        with pytest.raises(ValueError):
            await storage.put("../../etc/passwd", b"x", "text/plain")

    async def test_default_root_uses_repo_data_dir_not_cwd(self):
        # Regression: LocalStorage() used to default to the cwd-relative
        # string "data/uploads", so running any script or test from
        # backend/ as cwd silently created a stray backend/data/uploads
        # tree instead of writing into the repo's shared data/ directory
        # (the one Docker bind-mounts and .gitignore actually covers).
        storage = LocalStorage()
        assert storage._root == paths.data_dir() / "uploads"
