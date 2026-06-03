"""Shared constants and connection helpers for Milvus vector stores."""

import warnings

from pymilvus import PyMilvusDeprecationWarning, connections

from core import settings

# BGE-large-zh embedding dimension
DIM = 1024


def get_milvus_connection(alias: str = "default") -> str:
    """Get or create a Milvus connection.

    Args:
        alias: Connection alias. Different stores can use different aliases.

    Returns:
        The connection alias string.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PyMilvusDeprecationWarning)
        if not connections.has_connection(alias):
            connections.connect(
                alias=alias,
                host=settings.milvus_host,
                port=settings.milvus_port,
                user=settings.milvus_user or None,
                password=settings.milvus_password or None,
            )
    return alias
