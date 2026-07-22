class ResearchToolError(Exception):
    """Base error shown to command-line users."""


class ConfigurationError(ResearchToolError):
    """Configuration is missing or invalid."""


class KnowledgeError(ResearchToolError):
    """Knowledge storage operation failed."""


class IndexError(ResearchToolError):
    """RAG index operation failed."""


class ProviderError(ResearchToolError):
    """LLM provider operation failed."""


class ResearchFailedError(ResearchToolError):
    """Research completed without any usable result."""
