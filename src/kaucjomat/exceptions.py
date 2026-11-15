"""Wyjątki domenowe i konfiguracyjne symulatora KaucjaSim DEMO."""

from __future__ import annotations


class KaucjomatError(Exception):
    """Bazowy wyjątek domenowy aplikacji przenoszący kod błędu oraz status HTTP."""

    message: str
    error_code: str = "KAUCJOMAT_ERROR"
    status_code: int = 400

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        """Inicjalizuje wyjątek domenowy z czytelnym komunikatem po polsku."""
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class InvalidConfigurationError(KaucjomatError):
    """Wyjątek sygnalizujący nieprawidłową konfigurację lub błędny parametr wejściowy."""

    error_code: str = "INVALID_CONFIGURATION"
    status_code: int = 400


class ViewNotFoundError(KaucjomatError):
    """Wyjątek zgłaszany przy żądaniu nieistniejącego widoku powłoki webowej."""

    error_code: str = "VIEW_NOT_FOUND"
    status_code: int = 404


class PackageCardNotFoundError(KaucjomatError):
    """Wyjątek zgłaszany przy żądaniu nieistniejącej karty testowej opakowania."""

    error_code: str = "PACKAGE_CARD_NOT_FOUND"
    status_code: int = 404


class InvalidDepositRequestError(KaucjomatError):
    """Wyjątek zgłaszany dla niekompletnego lub sprzecznego żądania wrzutu opakowania."""

    error_code: str = "INVALID_DEPOSIT_REQUEST"
    status_code: int = 400


class ReturnStateStorageError(KaucjomatError):
    """Wyjątek sygnalizujący błąd odczytu lub zapisu lokalnego pliku stanu zwrotów."""

    error_code: str = "RETURN_STATE_STORAGE_ERROR"
    status_code: int = 500
