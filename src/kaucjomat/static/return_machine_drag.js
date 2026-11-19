/**
 * Przeciąganie kart opakowań z półki do okrągłego wlotu butelkomatu DEMO (Pointer Events: mysz, pióro i dotyk).
 * Moduł nie dotyka DOM przy ładowaniu; cała praca zaczyna się po wywołaniu `attachShelfDrag`.
 */
(function registerReturnDrag(globalScope) {
  const DRAG_THRESHOLD_PX = 4;
  const DESKTOP_QUERY = "(min-width: 821px)";
  const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
  const DROP_MS = 350;
  const RETURN_MS = 260;
  const GHOST_TILT_DEG = 4;

  /**
   * Sprawdza media query; bez `matchMedia` (np. w testach) zwraca wartość zastępczą.
   * @param {string} query - Zapytanie mediów CSS.
   * @param {boolean} fallback - Wynik, gdy przeglądarka nie udostępnia `matchMedia`.
   * @returns {boolean} Czy zapytanie jest spełnione.
   */
  function mediaMatches(query, fallback) {
    return typeof globalScope.matchMedia === "function" ? globalScope.matchMedia(query).matches : fallback;
  }

  /**
   * Rozstrzyga, czy punkt leży w okręgu wpisanym w prostokąt wlotu (promień = połowa krótszego boku).
   * @param {{x: number, y: number}} point - Pozycja wskaźnika w pikselach okna.
   * @param {{left: number, top: number, width: number, height: number}} rect - Prostokąt wlotu (jak z `getBoundingClientRect`).
   * @returns {boolean} Prawda, gdy punkt jest w okręgu (krawędź liczy się jako trafienie).
   */
  function isPointInsideInlet(point, rect) {
    const radius = Math.min(rect.width, rect.height) / 2;
    if (!(radius > 0)) return false;
    const dx = point.x - (rect.left + rect.width / 2);
    const dy = point.y - (rect.top + rect.height / 2);
    return Math.hypot(dx, dy) <= radius;
  }

  /**
   * Podpina delegowane przeciąganie ilustracji kart z półki do wlotu automatu.
   * @param {HTMLElement} shelf - Kontener półki; karty mogą być przeładowywane bez ponownego podpinania.
   * @param {HTMLElement} dropzone - Okrągły wlot, który podświetla się nad trafieniem.
   * @param {(cardId: string) => void} onDrop - Wywoływane od razu po upuszczeniu w okręgu wlotu.
   * @returns {void}
   */
  function attachShelfDrag(shelf, dropzone, onDrop) {
    const doc = globalScope.document;
    let drag = null;

    /** Czy wolno zacząć przeciąganie: układ dwukolumnowy i brak trwającej mutacji stanu DEMO. */
    function canStart() {
      const demo = globalScope.KaucjomatDemo;
      return mediaMatches(DESKTOP_QUERY, true) && !(demo && demo.busy);
    }

    /** Ustawia ducha pod wskaźnikiem (tylko transform) i podświetla wlot; wywoływane z rAF. */
    function renderFrame() {
      if (!drag) return;
      drag.frame = 0;
      const x = drag.x - drag.grabX;
      const y = drag.y - drag.grabY;
      drag.ghost.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${GHOST_TILT_DEG}deg)`;
      dropzone.classList.toggle("is-drop-target", isPointInsideInlet({ x: drag.x, y: drag.y }, drag.inletRect));
    }

    /** Planuje jedną aktualizację ducha na klatkę, niezależnie od liczby zdarzeń ruchu. */
    function requestFrame() {
      if (drag && !drag.frame) drag.frame = globalScope.requestAnimationFrame(renderFrame);
    }

    /** Odświeża zapamiętany prostokąt wlotu po przewinięciu lub zmianie rozmiaru okna. */
    function refreshInlet() {
      if (drag && drag.started) {
        drag.inletRect = dropzone.getBoundingClientRect();
        requestFrame();
      }
    }

    /** Tworzy ducha (klon ilustracji) i przygasza kartę źródłową po przekroczeniu progu ruchu. */
    function beginGhost() {
      const rect = drag.art.getBoundingClientRect();
      const ghost = drag.art.cloneNode(true);
      ghost.classList.add("package-drag-ghost");
      ghost.setAttribute("aria-hidden", "true");
      ghost.style.width = `${rect.width}px`;
      ghost.style.height = `${rect.height}px`;
      drag.grabX = drag.startX - rect.left;
      drag.grabY = drag.startY - rect.top;
      drag.inletRect = dropzone.getBoundingClientRect();
      drag.card.classList.add("is-dragging");
      doc.body.appendChild(ghost);
      drag.ghost = ghost;
      drag.started = true;
    }

    /**
     * Animuje ducha do punktu docelowego i usuwa go; przy ograniczonym ruchu usuwa go od razu.
     * Usunięcie idzie z timera, bo przy wyłączonych animacjach CSS nie powstałoby zdarzenie końca.
     */
    function settleGhost(session, className, toX, toY, durationMs) {
      const { ghost, card } = session;
      const finish = () => { ghost.remove(); card.classList.remove("is-dragging"); };
      if (mediaMatches(REDUCED_MOTION_QUERY, false)) { finish(); return; }
      ghost.style.setProperty("--drag-from-x", `${session.x - session.grabX}px`);
      ghost.style.setProperty("--drag-from-y", `${session.y - session.grabY}px`);
      ghost.style.setProperty("--drag-to-x", `${toX}px`);
      ghost.style.setProperty("--drag-to-y", `${toY}px`);
      ghost.style.setProperty("--drag-ms", `${durationMs}ms`);
      ghost.classList.add(className);
      globalScope.setTimeout(finish, durationMs);
    }

    /** Odsyła ducha na miejsce ilustracji w karcie (anulowanie lub upuszczenie poza wlotem). */
    function returnToShelf(session) {
      const home = session.art.getBoundingClientRect();
      settleGhost(session, "is-returning", home.left, home.top, RETURN_MS);
    }

    /** Wpuszcza ducha do środka wlotu; sam wrzut rusza natychmiast i nie czeka na animację. */
    function dropIntoInlet(session, inletRect) {
      onDrop(session.cardId);
      const toX = inletRect.left + inletRect.width / 2 - session.ghost.offsetWidth / 2;
      const toY = inletRect.top + inletRect.height / 2 - session.ghost.offsetHeight / 2;
      settleGhost(session, "is-dropping", toX, toY, DROP_MS);
    }

    /** Kończy bieżące przeciąganie: zdejmuje nasłuchy, capture i podświetlenie, zwraca zamkniętą sesję. */
    function endDrag() {
      const session = drag;
      drag = null;
      globalScope.removeEventListener("pointermove", onMove);
      globalScope.removeEventListener("pointerup", onUp);
      globalScope.removeEventListener("pointercancel", cancelDrag);
      globalScope.removeEventListener("lostpointercapture", cancelDrag);
      globalScope.removeEventListener("keydown", onKey);
      globalScope.removeEventListener("scroll", refreshInlet, true);
      globalScope.removeEventListener("resize", refreshInlet);
      if (session.frame) globalScope.cancelAnimationFrame(session.frame);
      try { session.art.releasePointerCapture(session.pointerId); } catch (error) { /* capture mogło już wygasnąć */ }
      dropzone.classList.remove("is-drop-target");
      return session;
    }

    /** Przerywa przeciąganie bez wrzutu: duch wraca na kartę (pointercancel, Escape, utrata capture). */
    function cancelDrag(event) {
      if (!drag || (event && event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
      const session = endDrag();
      if (session.started) returnToShelf(session);
    }

    /** Obsługuje klawisz Escape w trakcie przeciągania. */
    function onKey(event) {
      if (event.key === "Escape") cancelDrag();
    }

    /** Śledzi wskaźnik: po przekroczeniu progu tworzy ducha, potem tylko zapamiętuje pozycję. */
    function onMove(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (!drag.started) {
        if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) <= DRAG_THRESHOLD_PX) return;
        if (!canStart()) { endDrag(); return; }
        beginGhost();
      }
      requestFrame();
    }

    /** Puszczenie wskaźnika: trafienie w okrąg wpuszcza kartę do wlotu, w przeciwnym razie duch wraca. */
    function onUp(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      const inletRect = dropzone.getBoundingClientRect();
      const session = endDrag();
      if (!session.started) return;
      const demo = globalScope.KaucjomatDemo;
      const isBusy = Boolean(demo && demo.busy);
      if (!isBusy && isPointInsideInlet({ x: session.x, y: session.y }, inletRect)) dropIntoInlet(session, inletRect);
      else returnToShelf(session);
    }

    /** Początek gestu na ilustracji karty (nie na przycisku): rejestruje sesję i przechwytuje wskaźnik. */
    function onDown(event) {
      if (drag || !event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
      const art = event.target && event.target.closest ? event.target.closest(".package-card-art") : null;
      if (!art || !shelf.contains(art) || !canStart()) return;
      const card = art.closest(".package-card");
      const cardId = card && card.dataset ? card.dataset.cardId : "";
      if (!cardId) return;
      drag = {
        art, card, cardId, pointerId: event.pointerId, started: false, frame: 0,
        startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY,
      };
      try { art.setPointerCapture(event.pointerId); } catch (error) { /* bez capture ruch nadal śledzi okno */ }
      globalScope.addEventListener("pointermove", onMove);
      globalScope.addEventListener("pointerup", onUp);
      globalScope.addEventListener("pointercancel", cancelDrag);
      globalScope.addEventListener("lostpointercapture", cancelDrag);
      globalScope.addEventListener("keydown", onKey);
      globalScope.addEventListener("scroll", refreshInlet, true);
      globalScope.addEventListener("resize", refreshInlet);
    }

    shelf.addEventListener("pointerdown", onDown);
    // Długie przytrzymanie na dotyku otwierałoby menu kontekstowe i przerywało gest.
    shelf.addEventListener("contextmenu", (event) => { if (drag && drag.started) event.preventDefault(); });
  }

  globalScope.KaucjomatReturnDrag = { attachShelfDrag, isPointInsideInlet };
})(window);
