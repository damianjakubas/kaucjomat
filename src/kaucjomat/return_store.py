"""Bezpieczny wątkowo magazyn stanu rejestru zwróconych egzemplarzy i sesji DEMO."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from kaucjomat.checkout_domain import RedemptionMode, SettlementResult
from kaucjomat.checkout_redemption import CheckoutSnapshot, prepare_redemption
from kaucjomat.exceptions import (
    EmptyReturnSessionError,
    InvalidConfigurationError,
    InvalidDepositRequestError,
    KaucjomatError,
    ReturnStateStorageError,
    SessionVoucherConflictError,
)
from kaucjomat.logging_config import get_logger, sanitize_for_log
from kaucjomat.return_domain import (
    DecisionStatus,
    DepositDecision,
    PackageCandidate,
    evaluate_package_return,
)
from kaucjomat.return_state_codec import (
    ReturnSessionSnapshot,
    SessionAttemptRecord,
    attempt_dict_to_record,
    build_session_snapshot,
    create_empty_state,
    create_open_session_dict,
    decision_to_attempt_dict,
    validate_state_payload,
)
from kaucjomat.voucher_domain import (
    VoucherRecord,
    create_expired_test_voucher,
    create_issued_voucher,
)
from kaucjomat.voucher_state_codec import voucher_record_to_dict

__all__ = [
    "ReturnSessionSnapshot",
    "ReturnStateStore",
    "SessionAttemptRecord",
    "VoucherRecord",
]


class ReturnStateStore:
    """Magazyn stanu rejestru zwróconych sztuk i aktywnej sesji DEMO w pliku JSON."""

    def __init__(self, state_file: Path) -> None:
        """Inicjalizuje magazyn ze ścieżką pliku JSON i blokadą wątkową."""
        self._lock = threading.Lock()
        self._state_file = Path(state_file)
        self._logger = get_logger("returns.store")

    def get_session_snapshot(self) -> ReturnSessionSnapshot:
        """Bezpiecznie wątkowo wczytuje lub inicjalizuje stan i zwraca migawkę sesji."""
        with self._lock:
            state, parsed_attempts, _, needs_save = self._load_state()
            # Zapis przy inicjalizacji lub migracji zapewnia spójny identyfikator i listę bonów.
            if needs_save:
                self._save_state(state)
            return build_session_snapshot(state, parsed_attempts)

    def list_vouchers(self) -> tuple[VoucherRecord, ...]:
        """Zwraca listę wszystkich bonów DEMO z aktualizacją statusu i ewentualną migracją."""
        with self._lock:
            state, _, parsed_vouchers, needs_save = self._load_state()
            if needs_save:
                self._save_state(state)
            return parsed_vouchers

    def get_checkout_snapshot(self) -> CheckoutSnapshot:
        """Odczytuje bony i stabilną generację, utrwalając inicjalizację lub migrację."""
        with self._lock:
            state, _, vouchers, needs_save = self._load_state()
            if needs_save:
                self._save_state(state)
            return CheckoutSnapshot(state["demo_generation_id"], vouchers)

    def redeem_voucher(
        self, operation_id: str, demo_generation_id: str, voucher_code: str,
        redemption_mode: RedemptionMode | str, items: Sequence[Mapping[str, object]],
    ) -> tuple[SettlementResult, bool]:
        """Zużywa bon i zapisuje wynik w jednej transakcji albo odtwarza wcześniejszy wynik."""
        with self._lock:
            try:
                state, _, _, _ = self._load_state()
                result, replayed = prepare_redemption(
                    state, operation_id, demo_generation_id, voucher_code, redemption_mode, items,
                )
                if not replayed:
                    self._save_state(state)
            except ReturnStateStorageError:
                raise  # Odczyt i zapis rejestrują awarię, bez potwierdzania realizacji.
            except KaucjomatError as exc:
                self._logger.warning(
                    "Odmowa realizacji bonu DEMO %s (%s): %s.",
                    sanitize_for_log(voucher_code), sanitize_for_log(redemption_mode), exc.error_code,
                )
                raise
            self._logger.info(
                "%s bonu DEMO %s (%s): do zapłaty %d gr, wypłata %d gr.",
                "Odtworzono wynik realizacji" if replayed else "Zapisano realizację",
                sanitize_for_log(result.voucher_code), sanitize_for_log(result.redemption_mode),
                result.amount_due_grosze, result.cash_payout_grosze,
            )
            return result, replayed

    def process_deposit(
        self,
        candidate: PackageCandidate,
        card_id: str | None = None,
    ) -> tuple[DepositDecision, ReturnSessionSnapshot]:
        """Ocenia wrzut opakowania, aktualizuje stan pod blokadą i zapisuje plik JSON."""
        with self._lock:
            state, parsed_attempts, _, _ = self._load_state()
            returned_ids: set[str] = set(state["returned_instance_ids"])
            decision = evaluate_package_return(candidate, returned_ids)

            session = state["session"]
            if decision.status == DecisionStatus.ACCEPTED:
                session["accepted_count"] += 1
                session["total_grosze"] += decision.deposit_grosze
                if (
                    decision.instance_id is not None
                    and decision.instance_id not in returned_ids
                ):
                    state["returned_instance_ids"].append(decision.instance_id)
            elif decision.status == DecisionStatus.REDIRECT_TO_CASHIER:
                session["redirected_glass_count"] += 1
            else:
                session["rejected_count"] += 1

            # Numer próby po inkrementacji liczników pozostaje spójny także przy skróceniu historii.
            attempt_no = (
                session["accepted_count"]
                + session["redirected_glass_count"]
                + session["rejected_count"]
            )
            attempt_dict = decision_to_attempt_dict(attempt_no, card_id, decision)
            new_record = attempt_dict_to_record(attempt_dict)
            # Najnowsza próba trafia na początek listy historii wyświetlanej na panelu DEMO.
            session["attempts"].insert(0, attempt_dict)

            self._save_state(state)
            snapshot = build_session_snapshot(state, (new_record, *parsed_attempts))
            return decision, snapshot

    def issue_voucher(
        self,
        expected_session_id: str | None = None,
    ) -> tuple[VoucherRecord, ReturnSessionSnapshot, bool]:
        """Zamyka aktywną sesję z dodatnim saldem, wystawia bon DEMO i otwiera nową sesję."""
        with self._lock:
            state, parsed_attempts, parsed_vouchers, needs_save = self._load_state()
            if needs_save:
                self._save_state(state)

            session = state["session"]
            current_session_id = str(session["session_id"])

            if expected_session_id is not None:
                normalized_session_id = expected_session_id.strip()
                if not normalized_session_id:
                    raise InvalidDepositRequestError(
                        "Identyfikator sesji (session_id) nie może być pusty."
                    )
                if normalized_session_id != current_session_id:
                    matching_voucher = next(
                        (
                            voucher
                            for voucher in parsed_vouchers
                            if voucher.source_session_id == normalized_session_id
                            and not voucher.is_test_seed
                        ),
                        None,
                    )
                    if matching_voucher is not None:
                        self._logger.info(
                            "Idempotentne ponowienie wystawienia bonu DEMO dla sesji %s (%s).",
                            sanitize_for_log(normalized_session_id),
                            sanitize_for_log(matching_voucher.voucher_code),
                        )
                        return (
                            matching_voucher,
                            build_session_snapshot(state, parsed_attempts),
                            True,
                        )
                    raise SessionVoucherConflictError(
                        f"Sesja '{sanitize_for_log(normalized_session_id)}' nie jest aktywna i nie ma wystawionego bonu DEMO."
                    )

            total_grosze = int(session["total_grosze"])
            if total_grosze <= 0:
                raise EmptyReturnSessionError(
                    "Nie można wystawić bonu DEMO dla sesji o kwocie 0,00 zł — wrzuć co najmniej jedno akceptowane opakowanie PET lub puszkę."
                )

            sequence_no = (
                sum(1 for item in state["vouchers"] if not item.get("is_test_seed", False)) + 1
            )
            voucher = create_issued_voucher(
                sequence_no=sequence_no,
                source_session_id=current_session_id,
                amount_grosze=total_grosze,
                accepted_count=int(session["accepted_count"]),
            )
            state["vouchers"].insert(0, voucher_record_to_dict(voucher))
            # Zastępujemy wyłącznie aktywną sesję; returned_instance_ids pozostaje nienaruszone.
            state["session"] = create_open_session_dict()
            self._save_state(state)
            self._logger.info(
                "Wystawiono bon DEMO %s dla sesji %s na kwotę %s (nowa sesja: %s).",
                voucher.voucher_code,
                sanitize_for_log(voucher.source_session_id),
                voucher.amount_formatted,
                state["session"]["session_id"],
            )
            return voucher, build_session_snapshot(state, ()), False

    def reset_demo_state(self) -> ReturnSessionSnapshot:
        """Czyści trwały rejestr zwróconych ID oraz rozpoczyna nową czystą sesję DEMO."""
        with self._lock:
            state = create_empty_state()
            self._save_state(state)
            self._logger.info(
                "Zresetowano stan rejestru i sesji DEMO (nowa sesja: %s).",
                state["session"]["session_id"],
            )
            return build_session_snapshot(state, ())

    def _load_state(
        self,
    ) -> tuple[dict[str, Any], tuple[SessionAttemptRecord, ...], tuple[VoucherRecord, ...], bool]:
        """Wczytuje i waliduje stan z pliku JSON lub tworzy czysty stan początkowy."""
        if not self._state_file.exists():
            return create_empty_state(), (), (create_expired_test_voucher(),), True

        try:
            raw_text = self._state_file.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
            validated, parsed_attempts, parsed_vouchers, migrated = validate_state_payload(parsed)
            return validated, parsed_attempts, parsed_vouchers, migrated
        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            KeyError,
            InvalidConfigurationError,
        ) as exc:
            self._logger.error(
                "Nie udało się wczytać pliku stanu zwrotów DEMO.",
                exc_info=True,
            )
            raise ReturnStateStorageError(
                "Nie udało się odczytać zapisanego stanu sesji zwrotów DEMO."
            ) from exc

    def _save_state(self, state: dict[str, Any]) -> None:
        """Zapisuje stan magazynu atomowo przez plik tymczasowy i zamianę ścieżki."""
        tmp_path = self._state_file.with_name(f"{self._state_file.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False)
            tmp_path.write_text(serialized, encoding="utf-8")
            tmp_path.replace(self._state_file)
        except (OSError, ValueError) as exc:
            # Ignorujemy błąd sprzątania, jeśli np. katalog nadrzędny nie mógł zostać utworzony.
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)
            self._logger.error(
                "Nie udało się zapisać pliku stanu zwrotów DEMO.",
                exc_info=True,
            )
            raise ReturnStateStorageError(
                "Nie udało się zapisać aktualnego stanu sesji zwrotów DEMO."
            ) from exc
