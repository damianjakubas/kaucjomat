"""Dekorator metody sprawdzający aktywność bonu konkretnego obiektu rozliczenia."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar

from kaucjomat.checkout_exceptions import VoucherAlreadyRedeemedError, VoucherExpiredError
from kaucjomat.voucher_domain import VoucherStatus, resolve_voucher_status

if TYPE_CHECKING:
    from kaucjomat.checkout_domain import VoucherSettlement

P = ParamSpec("P")
R = TypeVar("R")


def require_active_voucher(
    method: Callable[Concatenate[VoucherSettlement, P], R],
) -> Callable[Concatenate[VoucherSettlement, P], R]:
    """Chroni metodę rozliczenia, odczytując bon i jawny czas oceny z jej `self`."""

    @wraps(method)
    def wrapper(self: VoucherSettlement, *args: P.args, **kwargs: P.kwargs) -> R:
        """Odrzuca bon zużyty lub wygasły przed wykonaniem obliczeń rozliczenia."""
        status = resolve_voucher_status(
            self.voucher.status, self.voucher.expires_at_iso, now=self.now
        )
        if status == VoucherStatus.REDEEMED:
            raise VoucherAlreadyRedeemedError("Bon DEMO został już zużyty.")
        if status == VoucherStatus.EXPIRED:
            raise VoucherExpiredError("Bon DEMO wygasł i nie może zostać zrealizowany.")
        return method(self, *args, **kwargs)

    return wrapper
