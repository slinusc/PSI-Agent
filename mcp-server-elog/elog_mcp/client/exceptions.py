"""Minimal exception definitions to satisfy local testing imports."""

__all__ = [
    "LogbookError",
    "LogbookServerTimeout",
    "LogbookServerProblem",
    "LogbookInvalidMessageID",
    "LogbookMessageRejected",
    "LogbookInvalidAttachment",
    "LogbookInvalidAttachmentType",
    "LogbookAuthenticationError",
]


class LogbookError(Exception):
    """Base exception for Logbook client errors."""


class LogbookServerTimeout(LogbookError):
    """Raised when the logbook server times out."""


class LogbookServerProblem(LogbookError):
    """Raised when the logbook server returns an error response."""


class LogbookInvalidMessageID(LogbookError):
    """Raised when an invalid message ID is referenced."""


class LogbookMessageRejected(LogbookError):
    """Raised when a logbook message is rejected."""


class LogbookInvalidAttachment(LogbookError):
    """Raised when an invalid attachment is supplied."""


class LogbookInvalidAttachmentType(LogbookInvalidAttachment):
    """Raised when an attachment has an unsupported type."""


class LogbookAuthenticationError(LogbookError):
    """Raised when authentication with the logbook fails."""
