class AppBaseException(Exception):
    """Base exception for all domain-specific errors."""
    pass

class UserAlreadyExistsException(AppBaseException):
    """Raised when trying to register an email that is already in use."""
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Email '{email}' is already registered.")