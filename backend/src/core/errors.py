from enum import Enum


class ErrorLevel(str, Enum):
    IGNORABLE = "ignorable"  # Log and continue (e.g., empty retrieval)
    CRITICAL = "critical"    # Raise and abort (e.g., Milvus down)


class RAGError(Exception):
    def __init__(self, message: str, level: ErrorLevel = ErrorLevel.CRITICAL):
        self.message = message
        self.level = level
        super().__init__(message)


class RetrievalError(RAGError):
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.IGNORABLE)


class VectorStoreError(RAGError):
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.CRITICAL)


class LLMError(RAGError):
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.CRITICAL)