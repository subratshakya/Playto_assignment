class InsufficientFundsError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


class InvalidStateTransitionError(Exception):
    pass
