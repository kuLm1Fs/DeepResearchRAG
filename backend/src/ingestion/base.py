from abc import ABC, abstractmethod
from typing import Any, Iterator


class BaseCollector(ABC):
    """Abstract base class for data collectors."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def collect(self, **kwargs) -> Iterator[dict[str, Any]]:
        """
        Collect data and yield records.

        Each record should have:
        - title: str
        - content: str
        - source: str
        - language: str
        - category: str (optional)
        - published_at: int (timestamp)
        """
        pass

    def collect_batch(self, batch_size: int = 100, **kwargs) -> list[dict[str, Any]]:
        """Collect a batch of records."""
        batch = []
        for record in self.collect(**kwargs):
            batch.append(record)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch