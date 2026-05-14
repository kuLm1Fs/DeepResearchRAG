from enum import Enum


class ErrorLevel(str, Enum):
    IGNORABLE = "ignorable"  # Log and continue (e.g., empty retrieval)
    HANDLED = "handled"      # Handled with fallback (e.g., embedding failed)
    CRITICAL = "critical"    # Raise and abort (e.g., Milvus down)
    NEEDS_ATTENTION = "needs_attention"  # Unknown errors requiring review


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


class EmbeddingError(RAGError):
    """Embedding 错误"""
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.HANDLED)


class ConfigError(RAGError):
    """配置错误 - 启动失败"""
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.CRITICAL)


class DatabaseError(RAGError):
    """数据库错误 - 连接或查询失败"""
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.CRITICAL)


class DataError(RAGError):
    """数据错误（格式、解析等）"""
    def __init__(self, message: str):
        super().__init__(message, ErrorLevel.IGNORABLE)


def handle_error(error: Exception, context: str = "") -> dict:
    """统一错误处理，返回结构化信息"""
    if isinstance(error, RAGError):
        level = error.level
        message = error.message
    else:
        level = ErrorLevel.NEEDS_ATTENTION
        message = str(error)

    return {
        "level": level.value,
        "message": message,
        "context": context,
        "action": _get_action(level)
    }


def _get_action(level: ErrorLevel) -> str:
    """根据错误级别返回处理建议"""
    actions = {
        ErrorLevel.IGNORABLE: "log_and_continue",
        ErrorLevel.HANDLED: "use_fallback",
        ErrorLevel.CRITICAL: "fail_fast",
    }
    # NEEDS_ATTENTION 默认归入 alert_and_log
    return actions.get(level, "alert_and_log")