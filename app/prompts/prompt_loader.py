"""Load prompt templates by name and locale, with fallback to English."""

import os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_DEFAULT_LOCALE = os.environ.get("MCPER_LOCALE", "en")


def load_prompt(name: str, locale: str | None = None) -> str:
    """
    Load a prompt template by name and locale.

    Falls back to 'en' if the requested locale file does not exist.

    Args:
        name: Prompt file name without extension (e.g., 'global_rule_bootstrap')
        locale: Language code ('en' or 'ko'). Defaults to MCPER_LOCALE env var or 'en'.

    Returns:
        Prompt template content as string.

    Raises:
        FileNotFoundError: If neither the requested locale nor English fallback exists.
    """
    locale = locale or _DEFAULT_LOCALE
    path = _PROMPTS_DIR / locale / f"{name}.md"

    if not path.exists():
        # Fallback to English
        fallback_path = _PROMPTS_DIR / "en" / f"{name}.md"
        if fallback_path.exists():
            return fallback_path.read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"Prompt '{name}' not found in locale '{locale}' or fallback 'en': "
            f"tried {path} and {fallback_path}"
        )

    return path.read_text(encoding="utf-8")
