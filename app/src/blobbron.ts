// Een mediabestand één keer helemaal ophalen en als `blob:`-adres teruggeven.
//
// Waarom (15-10-2026): een `<video>` of `<audio>` met een `tauri://`- of
// `asset://`-adres vraagt het bestand in stukjes op (Range-verzoeken) en breekt
// die af zodra je pauzeert, terugspoelt of het element weghaalt. Bij het
// scrollen door de montagestijlen gebeurde dat tientallen keren per seconde
// (elke tegel speelt onder de muis). Een afgebroken verzoek waar de Rust-kant
// nog op antwoordt laat de webview-laag (wry, WKURLSchemeTask) de hele app
// afbreken — Koens crash van 15-10 00:05. Een `blob:`-adres gaat niet meer
// over dat protocol, dus er valt niets meer af te breken.
//
// `blobBron` onthoudt: alleen voor kleine bestanden die vaak terugkomen (de
// tegels, ~300 KB). `blobLos` onthoudt niet: voor de muziekvarianten. Geen
// van beide voor proxies of de export.

const cache = new Map<string, Promise<string>>();

export function blobBron(url: string): Promise<string> {
  let bron = cache.get(url);
  if (bron === undefined) {
    bron = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`${url}: ${r.status}`);
        return r.blob();
      })
      .then((b) => URL.createObjectURL(b));
    // Mislukt: niet onthouden, zodat een volgende poging opnieuw kan.
    bron.catch(() => cache.delete(url));
    cache.set(url, bron);
  }
  return bron;
}

/** Eén keer ophalen zónder te onthouden: voor grote bestanden die maar even
 *  nodig zijn (muziekvarianten zijn WAV's van tientallen MB). De aanroeper
 *  ruimt op met `URL.revokeObjectURL`. */
export async function blobLos(url: string): Promise<string> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return URL.createObjectURL(await r.blob());
}

/** Voor de tests: hoeveel adressen er in het geheugen staan. */
export function blobAantal(): number {
  return cache.size;
}
