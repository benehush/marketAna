"""Typed errors for the standalone data-processing package."""


class DataProcessingError(Exception):
    """Base error for this package."""


class ReaderError(DataProcessingError):
    """Input file could not be converted to a Document."""


class LexiconError(DataProcessingError):
    """Instrument lexicon is invalid or unavailable."""


class LLMOutputError(DataProcessingError):
    """LLM output cannot be converted to a valid structured result."""
