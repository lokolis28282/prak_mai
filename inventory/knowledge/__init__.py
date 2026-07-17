"""Knowledge base module."""

from .facade import (
    KnowledgeError,
    KnowledgeFacade,
    KnowledgeNotFound,
    KnowledgePermissionError,
)

__all__ = [
    "KnowledgeError",
    "KnowledgeFacade",
    "KnowledgeNotFound",
    "KnowledgePermissionError",
]
