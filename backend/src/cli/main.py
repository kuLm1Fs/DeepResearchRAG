"""
CLI 入口 - 提供命令行接口进行数据采集、查询和统计
"""
import json
import sys
from typing import Any

import click

from core import get_logger, settings
from vectorstore import MilvusStore
from ingestion.pipeline import Pipeline
from retrieval.retriever import MultiPathRetriever

logger = get_logger(__name__)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    RAG News Intelligence CLI

    数据采集、查询和统计工具
    """
    pass


@cli.command()
@click.option("--source", "-s", type=str, help="指定采集源 (rss/hn/dataset)")
@click.option("--parallel/--serial", default=True, help="是否并行执行，默认并行")
def ingest(source: str | None, parallel: bool):
    """
    触发数据采集

    不指定 --source 时，采集所有已注册的采集器数据。
    """
    click.echo(f"[INFO] 开始数据采集 (parallel={parallel})")

    pipeline = Pipeline()
    pipeline.register_defaults()

    if source:
        # 单源采集
        if source not in pipeline.list_collectors():
            click.echo(f"[ERROR] 未知的采集源: {source}")
            click.echo(f"可用采集源: {', '.join(pipeline.list_collectors())}")
            sys.exit(1)

        click.echo(f"[INFO] 采集数据源: {source}")
        count = 0
        for article in pipeline.collect_one(source):
            count += 1
            if count <= 3:
                click.echo(f"  - {article.get('title', 'N/A')}")

        click.echo(f"[INFO] {source} 采集完成，共 {count} 条记录")
    else:
        # 全量采集
        click.echo(f"[INFO] 全量采集模式，共 {len(pipeline.list_collectors())} 个采集器")
        total_count = 0
        for article in pipeline.collect_all(parallel=parallel):
            total_count += 1
            if total_count <= 5:
                click.echo(f"  - {article.get('title', 'N/A')}")

        click.echo(f"[INFO] 全量采集完成，共 {total_count} 条记录")

    pipeline.shutdown()
    click.echo("[INFO] 数据采集任务结束")


@cli.command()
@click.option("--query", "-q", type=str, help="查询语句")
@click.option("--top-k", "-k", type=int, default=5, help="返回结果数量，默认5")
def query(query: str | None, top_k: int):
    """
    CLI 交互式查询

    不指定 --query 时，进入交互模式。
    """
    # 初始化 Milvus store 和检索器
    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    if query:
        # 单次查询模式
        _execute_query(retriever, query, top_k)
    else:
        # 交互模式
        click.echo("[INFO] 进入交互查询模式，输入 'quit' 或 'exit' 退出")
        click.echo("-" * 50)

        while True:
            try:
                user_input = click.prompt("查询")
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("[INFO] 退出查询")
                    break

                if not user_input.strip():
                    continue

                _execute_query(retriever, user_input, top_k)
            except KeyboardInterrupt:
                click.echo("\n[INFO] 退出查询")
                break


def _execute_query(retriever: MultiPathRetriever, query: str, top_k: int) -> None:
    """
    执行查询并打印结果

    Args:
        retriever: 检索器实例
        query: 查询语句
        top_k: 返回结果数量
    """
    click.echo(f"[QUERY] {query}")

    try:
        results = retriever.retrieve(query, top_k=top_k)

        if not results:
            click.echo("[RESULT] 未找到相关结果")
            return

        click.echo(f"[RESULT] 共找到 {len(results)} 条结果:")
        click.echo("-" * 50)

        for i, r in enumerate(results, 1):
            title = r.get("title", "N/A")
            score = r.get("score", 0.0)
            source = r.get("source", "N/A")
            click.echo(f"{i}. {title}")
            click.echo(f"   来源: {source} | 相关度: {score:.4f}")
            click.echo("-" * 50)

    except Exception as e:
        click.echo(f"[ERROR] 查询失败: {e}")


@cli.command()
@click.option("--json/--text", default=False, help="以 JSON 格式输出")
def stats(json_output: bool):
    """
    查看数据统计信息

    显示当前 Milvus 中的数据统计。
    """
    click.echo("[INFO] 获取数据统计...")

    try:
        store = MilvusStore()
        total = store.count()

        if json_output:
            output = {
                "total_articles": total,
                "milvus_host": settings.milvus_host,
                "milvus_port": settings.milvus_port,
                "collection": store.collection_name,
            }
            click.echo(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            click.echo("=" * 50)
            click.echo("RAG 数据统计")
            click.echo("=" * 50)
            click.echo(f"总文章数: {total}")
            click.echo(f"Milvus: {settings.milvus_host}:{settings.milvus_port}")
            click.echo(f"Collection: {store.collection_name}")
            click.echo("=" * 50)

    except Exception as e:
        click.echo(f"[ERROR] 获取统计失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()