/** Wspólna blokada mutacji i bilety odczytów w obrębie jednej strony DEMO. */
window.KaucjomatDemo = (() => {
  let epoch = 0;
  let busy = false;
  const counters = new Map();

  /** Powiadamia kontrolery o unieważnieniu starszych odczytów. */
  function notify(reason, phase) {
    epoch += 1;
    window.dispatchEvent(new CustomEvent("kaucjomat:state-changed", {
      detail: { reason, epoch, phase },
    }));
  }

  return {
    get busy() { return busy; },
    /** Rezerwuje stronę przed wysłaniem żądania mutującego. */
    begin(reason) {
      if (busy) return false;
      busy = true;
      notify(reason, "start");
      return true;
    },
    /** Zwalnia stronę także po awarii; odświeżenie rozstrzyga stan serwera. */
    end(reason) {
      busy = false;
      notify(reason, "end");
    },
    /** Nadaje odczytowi numer oraz epokę; nowszy odczyt unieważnia starszy. */
    read(key) {
      const sequence = (counters.get(key) || 0) + 1;
      counters.set(key, sequence);
      return { key, sequence, epoch };
    },
    /** Sprawdza aktualność zarówno sukcesu, jak i błędu odczytu. */
    current(ticket) {
      return !busy && ticket.epoch === epoch && counters.get(ticket.key) === ticket.sequence;
    },
  };
})();
