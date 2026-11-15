"""Bezpieczny wątkowo magazyn stanu rejestru zwróconych egzemplarzy i sesji DEMO."""

from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from kaucjomat.exceptions import ReturnStateStorageError
from kaucjomat.logging_config import get_logger
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
    decision_to_attempt_dict,
    validate_state_payload,
)

__all__ = ["ReturnSessionSnapshot", "ReturnStateStore", "SessionAttemptRecord"]


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
            state, parsed_attempts, initialized = self._load_state()
            # Zapis początkowego stanu zapewnia niezmienny identyfikator sesji od pierwszego odczytu.
            if initialized:
                self._save_state(state)
            return build_session_snapshot(state, parsed_attempts)

    def process_deposit(
        self,
        candidate: PackageCandidate,
        card_id: str | None = None,
    ) -> tuple[DepositDecision, ReturnSessionSnapshot]:
        """Ocenia wrzut opakowania, aktualizuje stan pod blokadą i zapisuje plik JSON."""
        with self._lock:
            state, parsed_attempts, _ = self._load_state()
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

    def _load_state(self) -> tuple[dict[str, Any], tuple[SessionAttemptRecord, ...], bool]:
        """Wczytuje i waliduje stan z pliku JSON lub tworzy czysty stan początkowy."""
        if not self._state_file.exists():
            return create_empty_state(), (), True

        try:
            raw_text = self._state_file.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
            validated, parsed_attempts = validate_state_payload(parsed)
            return validated, parsed_attempts, False
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
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
