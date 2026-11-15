"""Czytelne odmowy walidacji koszyka i rozliczenia bonu DEMO."""

from kaucjomat.exceptions import KaucjomatError


class InvalidCheckoutRequestError(KaucjomatError):
    """Sygnalizuje niepoprawne dane koszyka lub trybu rozliczenia."""

    error_code: str = "INVALID_CHECKOUT_REQUEST"
    status_code: int = 400


class VoucherAlreadyRedeemedError(KaucjomatError):
    """Blokuje nową realizację bonu wcześniej zużytego."""

    error_code: str = "VOUCHER_ALREADY_REDEEMED"
    status_code: int = 409


class VoucherExpiredError(KaucjomatError):
    """Blokuje realizację bonu po upływie terminu ważności."""

    error_code: str = "VOUCHER_EXPIRED"
    status_code: int = 409


class BasketTooSmallError(KaucjomatError):
    """Odrzuca zakupy o wartości mniejszej od wartości bonu."""

    error_code: str = "BASKET_TOO_SMALL"
    status_code: int = 409


class VoucherNotFoundError(KaucjomatError):
    """Sygnalizuje brak bonu o podanym kodzie w bieżącym pokazie DEMO."""

    error_code: str = "VOUCHER_NOT_FOUND"
    status_code: int = 404


class RedemptionOperationConflictError(KaucjomatError):
    """Blokuje użycie identyfikatora zakończonej operacji z inną treścią."""

    error_code: str = "CHECKOUT_OPERATION_CONFLICT"
    status_code: int = 409


class DemoGenerationConflictError(KaucjomatError):
    """Odrzuca żądanie pochodzące z pokazu sprzed resetu."""

    error_code: str = "DEMO_GENERATION_CONFLICT"
    status_code: int = 409
