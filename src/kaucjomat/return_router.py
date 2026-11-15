"""Router FastAPI dla operacji butelkomatu i sesji zwrotów KaucjaSim DEMO."""

from __future__ import annotations

from fastapi import APIRouter

from kaucjomat.exceptions import InvalidDepositRequestError
from kaucjomat.return_domain import (
    DepositDecision,
    PackageCandidate,
    format_pln_from_grosze,
)
from kaucjomat.return_schemas import (
    DepositAttemptResponse,
    DepositDecisionSchema,
    DepositRequest,
    ResetStateResponse,
    ReturnSessionSchema,
    SessionAttemptSchema,
    TestCardSchema,
    TestCardsListResponse,
)
from kaucjomat.return_store import ReturnSessionSnapshot, ReturnStateStore
from kaucjomat.test_cards import TestPackageCard, get_test_card_by_id, get_test_cards


def _to_test_card_schema(card: TestPackageCard) -> TestCardSchema:
    """Konwertuje definicję karty testowej na model odpowiedzi API."""
    return TestCardSchema(
        card_id=card.card_id,
        title=card.title,
        subtitle=card.subtitle,
        badge=card.badge,
        group=card.group,
        expected_hint=card.expected_hint,
        package_code=card.candidate.package_code,
        category=card.candidate.category,
        volume_ml=card.candidate.volume_ml,
        has_deposit_logo=card.candidate.has_deposit_logo,
        is_crushed=card.candidate.is_crushed,
        is_empty=card.candidate.is_empty,
    )


def _to_decision_schema(decision: DepositDecision) -> DepositDecisionSchema:
    """Konwertuje wynik walidacji domenowej na model JSON odpowiedzi API."""
    return DepositDecisionSchema(
        status=decision.status,
        reason_code=decision.reason_code,
        deposit_grosze=decision.deposit_grosze,
        deposit_formatted=format_pln_from_grosze(decision.deposit_grosze),
        cashier_suggested_grosze=decision.cashier_suggested_grosze,
        cashier_suggested_formatted=format_pln_from_grosze(decision.cashier_suggested_grosze),
        message=decision.message,
        package_code=decision.package_code,
        title=decision.title,
        category=decision.category,
        volume_ml=decision.volume_ml,
        ean=decision.ean,
        instance_id=decision.instance_id,
        elapsed_ms=decision.elapsed_ms,
        within_latency_budget=decision.within_latency_budget,
    )


def _to_session_schema(snapshot: ReturnSessionSnapshot) -> ReturnSessionSchema:
    """Konwertuje migawkę stanu z magazynu JSON na model odpowiedzi Pydantic."""
    return ReturnSessionSchema(
        mode="DEMO",
        session_id=snapshot.session_id,
        status=snapshot.status,
        accepted_count=snapshot.accepted_count,
        redirected_glass_count=snapshot.redirected_glass_count,
        rejected_count=snapshot.rejected_count,
        total_grosze=snapshot.total_grosze,
        total_formatted=snapshot.total_formatted,
        returned_registry_size=snapshot.returned_registry_size,
        can_issue_voucher=snapshot.can_issue_voucher,
        attempts=[
            SessionAttemptSchema(
                attempt_no=attempt.attempt_no,
                timestamp_iso=attempt.timestamp_iso,
                card_id=attempt.card_id,
                package_code=attempt.package_code,
                title=attempt.title,
                category=attempt.category,
                volume_ml=attempt.volume_ml,
                ean=attempt.ean,
                instance_id=attempt.instance_id,
                status=attempt.status,
                reason_code=attempt.reason_code,
                deposit_grosze=attempt.deposit_grosze,
                cashier_suggested_grosze=attempt.cashier_suggested_grosze,
                message=attempt.message,
                elapsed_ms=attempt.elapsed_ms,
            )
            for attempt in snapshot.attempts
        ],
    )


def _resolve_candidate_from_request(
    payload: DepositRequest,
) -> tuple[PackageCandidate, str | None]:
    """Rozstrzyga kandydata opakowania na podstawie card_id lub custom_candidate."""
    has_card_id = payload.card_id is not None
    has_custom = payload.custom_candidate is not None
    if has_card_id == has_custom:
        raise InvalidDepositRequestError(
            "Żądanie wrzutu musi zawierać dokładnie jedno źródło: card_id albo custom_candidate."
        )

    if payload.card_id is not None:
        normalized_card_id = payload.card_id.strip()
        if not normalized_card_id:
            raise InvalidDepositRequestError("Identyfikator karty testowej (card_id) nie może być pusty.")
        card = get_test_card_by_id(normalized_card_id)
        return card.candidate, card.card_id

    custom = payload.custom_candidate
    assert custom is not None
    candidate = PackageCandidate(
        package_code=custom.package_code,
        title=custom.title,
        category=custom.category,
        volume_ml=custom.volume_ml,
        has_deposit_logo=custom.has_deposit_logo,
        is_crushed=custom.is_crushed,
        is_empty=custom.is_empty,
    )
    return candidate, None


def create_return_router(store: ReturnStateStore) -> APIRouter:
    """Tworzy router FastAPI wystawiający endpointy zwrotów pod prefiksem ``/api/returns``."""
    router = APIRouter(prefix="/api/returns", tags=["returns"])

    @router.get("/cards", response_model=TestCardsListResponse)
    def list_test_cards() -> TestCardsListResponse:
        """Zwraca katalog 8 predefiniowanych kart testowych DEMO dla butelkomatu."""
        return TestCardsListResponse(
            mode="DEMO",
            cards=[_to_test_card_schema(card) for card in get_test_cards()],
        )

    @router.get("/session", response_model=ReturnSessionSchema)
    def read_return_session() -> ReturnSessionSchema:
        """Zwraca aktualny stan aktywnej sesji zwrotów oraz rozmiar rejestru DEMO."""
        return _to_session_schema(store.get_session_snapshot())

    @router.post("/deposit", response_model=DepositAttemptResponse)
    def submit_deposit(payload: DepositRequest) -> DepositAttemptResponse:
        """Ocenia wrzut pojedynczego opakowania i zwraca decyzję oraz zaktualizowaną sesję."""
        candidate, used_card_id = _resolve_candidate_from_request(payload)
        decision, snapshot = store.process_deposit(candidate, card_id=used_card_id)
        return DepositAttemptResponse(
            mode="DEMO",
            decision=_to_decision_schema(decision),
            session=_to_session_schema(snapshot),
        )

    @router.post("/reset", response_model=ResetStateResponse)
    def reset_return_state() -> ResetStateResponse:
        """Czyści trwały rejestr zwróconych egzemplarzy i otwiera nową sesję DEMO."""
        snapshot = store.reset_demo_state()
        return ResetStateResponse(
            mode="DEMO",
            message="Wyczyszczono rejestr zwróconych egzemplarzy oraz otwarto nową sesję DEMO.",
            session=_to_session_schema(snapshot),
        )

    return router
