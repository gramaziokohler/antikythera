class RequestedBlueprintNotFound(Exception):
    """Raised when a requested blueprint is not found in storage."""

    pass


class RequestedModelNotFound(Exception):
    """Raised when a requested model is not found in storage."""

    pass


class RequestedSessionNotFound(Exception):
    """Raised when a requested session is not found in storage."""

    pass
