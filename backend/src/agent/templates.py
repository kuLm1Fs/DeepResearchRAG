from pathlib import Path
from typing import Any

from core import get_logger, settings

logger = get_logger(__name__)

# Get prompt directory (with version switching)
def get_prompt_dir() -> Path:
    version = settings.prompt_version
    prompt_dir = settings.prompt_dir / version

    # Fallback to v1 if version doesn't exist
    if not prompt_dir.exists():
        logger.warning("prompt_version_not_found", version=version, fallback="v1")
        prompt_dir = settings.prompt_dir / "v1"

    return prompt_dir


def load_prompt(name: str, **kwargs: Any) -> str:
    """
    Load a prompt template and format with provided variables.

    Args:
        name: Template filename (without .txt extension)
        **kwargs: Variables to format the template with

    Returns:
        Formatted prompt string
    """
    prompt_dir = get_prompt_dir()
    template_path = prompt_dir / f"{name}.txt"

    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {template_path}")

    template = template_path.read_text()

    # Format with provided variables
    formatted = template.format(**kwargs)

    if settings.debug:
        logger.debug("prompt_loaded",
            prompt_name=name,
            prompt_version=settings.prompt_version,
            prompt_length=len(formatted),
            variables={k: str(v)[:100] for k, v in kwargs.items()},
        )

    return formatted


__all__ = ["load_prompt", "get_prompt_dir"]