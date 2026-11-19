/**
 * Mapowanie karty testowej opakowania na ilustrację SVG półki butelkomatu DEMO.
 * Wybór grafiki wynika z atrybutów karty (kategoria, pojemność, logo, zgniecenie), a nie z jej identyfikatora.
 */
(function registerReturnArt(globalScope) {
  const ART_BASE_PATH = "/static/assets/";
  const LARGE_VOLUME_ML = 3000;
  const SMALL_VOLUME_LIMIT_ML = 700;
  const LARGE_VOLUME_LIMIT_ML = 2500;

  /**
   * Wybiera nazwę pliku i opis alternatywny ilustracji na podstawie atrybutów karty.
   * @param {object} card - Metadane karty z `/api/returns/cards`.
   * @returns {{file: string, alt: string}} Nazwa pliku SVG (bez ścieżki) i polski opis.
   */
  function pickArtFile(card) {
    const volume = Number(card.volume_ml) || 0;
    if (card.is_crushed) return { file: "can-crushed.svg", alt: "Zgnieciona puszka aluminiowa" };
    if (card.category === "DAIRY_CARTON" || card.category === "OTHER") {
      return { file: "carton-milk.svg", alt: "Karton po mleku" };
    }
    if (card.category === "GLASS") return { file: "glass-500.svg", alt: "Butelka szklana zwrotna" };
    if (card.category === "CAN") return { file: "can-500.svg", alt: "Puszka aluminiowa" };
    if (card.category === "PET" && volume > LARGE_VOLUME_ML) return { file: "pet-jug-5000.svg", alt: "Baniak PET 5 l" };
    if (card.category === "PET" && card.has_deposit_logo === false) {
      return { file: "pet-500-no-logo.svg", alt: "Butelka PET bez znaku kaucji" };
    }
    return { file: "pet-1500.svg", alt: "Butelka PET ze znakiem kaucji" };
  }

  /**
   * Dobiera klasę rozmiaru ilustracji do pojemności opakowania.
   * @param {number} volumeMl - Pojemność opakowania w mililitrach.
   * @returns {string} Jedna z klas: `is-small`, `is-medium`, `is-large`.
   */
  function pickSizeClass(volumeMl) {
    const volume = Number(volumeMl) || 0;
    if (volume <= SMALL_VOLUME_LIMIT_ML) return "is-small";
    if (volume <= LARGE_VOLUME_LIMIT_ML) return "is-medium";
    return "is-large";
  }

  /**
   * Rozstrzyga ilustrację karty: ścieżkę pliku, opis alternatywny i klasę rozmiaru.
   * @param {object} card - Metadane karty z `/api/returns/cards`.
   * @returns {{src: string, alt: string, sizeClass: string}} Opis grafiki do wstawienia w kartę.
   */
  function resolvePackageArt(card) {
    const safeCard = card || {};
    const picked = pickArtFile(safeCard);
    return {
      src: `${ART_BASE_PATH}${picked.file}`,
      alt: picked.alt,
      sizeClass: pickSizeClass(safeCard.volume_ml),
    };
  }

  /**
   * Buduje element `<figure>` z ilustracją opakowania; to zaczep dla przeciągania kart.
   * @param {object} card - Metadane karty z `/api/returns/cards`.
   * @returns {HTMLElement} Element `<figure class="package-card-art">` z obrazkiem SVG.
   */
  function buildPackageFigure(card) {
    const art = resolvePackageArt(card);
    const figure = document.createElement("figure");
    figure.className = `package-card-art ${art.sizeClass}`;
    const image = document.createElement("img");
    image.src = art.src;
    image.alt = art.alt;
    image.className = "package-card-img";
    // Natywny drag obrazka przerywałby zdarzenia wskaźnika, więc wyłączamy go jawnie.
    image.draggable = false;
    figure.appendChild(image);
    return figure;
  }

  globalScope.KaucjomatReturnArt = { resolvePackageArt, buildPackageFigure };
})(window);
