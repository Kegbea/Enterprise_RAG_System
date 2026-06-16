"""批量文档导入脚本。

用法:
    uv run python -m scripts.ingest --dir data/documents --overwrite
    uv run python -m scripts.ingest  # 使用默认目录
"""

import argparse
import logging
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.etl.chunker import ChunkConfig
from app.etl.pipeline import ETLPipeline, InMemoryDocStore
from app.services.ingestion import IngestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest")


def main():
    parser = argparse.ArgumentParser(
        description="批量文档导入 — 扫描目录并入库",
    )
    parser.add_argument(
        "--dir",
        default=settings.document_archive_dir,
        help=f"文档目录路径（默认: {settings.document_archive_dir}）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的相同文档（checksum 匹配时）",
    )
    args = parser.parse_args()

    dir_path = Path(args.dir)
    if not dir_path.exists():
        logger.error(f"目录不存在: {dir_path}")
        sys.exit(1)

    logger.info("初始化存储和 ETL Pipeline...")
    store = InMemoryDocStore()
    chunk_config = ChunkConfig(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    pipeline = ETLPipeline(store, chunk_config=chunk_config)
    service = IngestionService(pipeline, archive_dir=settings.document_archive_path)

    logger.info(f"开始批量导入，目录: {dir_path}")
    batch = service.ingest_batch(dir_path, overwrite=args.overwrite)

    logger.info(f"\n{'='*50}")
    logger.info("批量导入完成")
    logger.info(f"  总计: {batch.total}")
    logger.info(f"  成功: {batch.succeeded}")
    logger.info(f"  覆盖: {batch.overwritten}")
    logger.info(f"  跳过: {batch.skipped}")
    logger.info(f"  失败: {batch.failed}")
    logger.info(f"{'='*50}")

    for item in batch.items:
        if item.status == "error":
            logger.warning(f"  ✗ {item.filename}: {item.error_message}")

    sys.exit(0 if batch.failed == 0 else 1)


if __name__ == "__main__":
    main()
