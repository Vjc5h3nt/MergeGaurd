"""Tree-sitter grammar loader — builds Language() registry for Py/TS/JS/Go/Java."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Supported languages and their file extensions
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "go": [".go"],
    "java": [".java"],
}

# Reverse map: extension -> language
_EXT_TO_LANG: dict[str, str] = {
    ext: lang
    for lang, exts in LANGUAGE_EXTENSIONS.items()
    for ext in exts
}

_PARSERS: dict[str, Any] = {}


def get_language_for_file(path: str) -> str | None:
    """Detect language from file extension."""
    suffix = Path(path).suffix.lower()
    return _EXT_TO_LANG.get(suffix)


def get_parser(language: str) -> Any:
    """Return a cached tree-sitter Parser for the given language name."""
    if language in _PARSERS:
        return _PARSERS[language]

    try:
        import tree_sitter_languages
        from tree_sitter import Language, Parser

        lang_obj = tree_sitter_languages.get_language(language)
        parser = Parser()
        parser.set_language(Language(lang_obj))  # type: ignore[arg-type]
        _PARSERS[language] = parser
        log.debug("Loaded tree-sitter parser for %s", language)
        return parser
    except Exception as exc:
        log.warning("Could not load tree-sitter parser for %s: %s", language, exc)
        return None


def parse_source(source: str, language: str) -> Any:
    """Parse source code string into a tree-sitter Tree.

    Returns None if the language is unsupported or parsing fails.
    """
    parser = get_parser(language)
    if parser is None:
        return None
    try:
        return parser.parse(source.encode("utf-8"))
    except Exception as exc:
        log.warning("Parse error for %s: %s", language, exc)
        return None


def parse_file(path: str, source: str) -> tuple[Any, str | None]:
    """Parse a source file, auto-detecting language.

    Returns (tree, language) or (None, None) if unsupported.
    """
    lang = get_language_for_file(path)
    if lang is None:
        return None, None
    tree = parse_source(source, lang)
    return tree, lang
