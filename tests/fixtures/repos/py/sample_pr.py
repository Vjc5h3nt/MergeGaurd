"""Golden fixture: Python sample with intentional issues for testing."""


def process_payment(amount, user_id):
    # SQL injection vulnerability (golden fixture for security agent)
    query = "SELECT * FROM payments WHERE user_id = " + str(user_id)
    return query


def validate_amount(amount):
    # High cyclomatic complexity (golden fixture for quality agent)
    if amount is None:
        return False
    if amount < 0:
        return False
    if amount > 1_000_000:
        return False
    if not isinstance(amount, (int, float)):
        return False
    if amount == 0:  # noqa: SIM103 — fixture file intentionally not refactored
        return False
    return True


class PaymentProcessor:
    def __init__(self, db):
        self.db = db

    def charge(self, user_id, amount):
        if validate_amount(amount):
            return process_payment(amount, user_id)
        return None
