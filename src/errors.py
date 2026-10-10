"""Public errors with credential-free messages."""


class ValidationError(ValueError):
    """A supplied value is invalid."""


class AccessDenied(PermissionError):
    """The credential does not authorize this operation."""


class NotFound(LookupError):
    """The requested resource is not visible."""


class Conflict(Exception):
    """An operation conflicts with existing state."""

    def __init__(self, message="Conflict", *, owner_member_id=None):
        super().__init__(message)
        self.owner_member_id = owner_member_id
