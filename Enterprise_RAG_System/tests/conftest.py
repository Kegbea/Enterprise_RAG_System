# tests/conftest.py — 共享 fixtures + 测试隔离配置
#
# ChromaDB 在当前 Windows 环境下存在 Rust binding 兼容性问题，
# 已切换为 InMemoryDocStore（基于 LlamaIndex SimpleDocumentStore）。
# 见 app/etl/pipeline.py。

import shutil
from pathlib import Path

import pytest

# 测试专用存储路径（隔离于生产 data/storage）
TEST_STORAGE_DIR = Path("data/test_storage")


@pytest.fixture(autouse=True)
def clean_test_storage():
    """每个测试前清理测试存储目录，确保隔离。"""
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
    yield
    # 测试后清理
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
