// De dialoog waarmee je een kopie weer een project maakt. Hij laat eerst zien
// wat er in het bestand zit en wat er gaat gebeuren; pas op de knop wordt er
// iets geschreven. Twee beloftes: er wordt nooit een project overschreven, en
// je eigen video's blijven waar ze zijn.
//
// Net als de verwijderdialoog een native <dialog>, in dezelfde vorm.
import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { projectKopie, projectTerugzetten } from "./engine";
import { grootteTekst } from "./verwijderkeuze";
import {
  bestandsnaam,
  bronnenTekst,
  datumTekst,
  naamUitleg,
  ontbrekend,
  TOON_ONTBREKEND,
  type Kopie,
  type Teruggezet,
} from "./terugzetkeuze";
import { EDITIE } from "./editie";

/** Even wachten na een toetsaanslag voor de engine de naam nakijkt. */
const NAAM_WACHT_MS = 250;

type Props = {
  /** Het zip-bestand dat de gebruiker koos. */
  pad: string;
  onSluit: () => void;
  onKlaar: (uit: Teruggezet) => void;
};

const schoon = (e: unknown) => String(e).replace(/^Error: /, "");

export default function TerugzetDialoog({ pad: eerste, onSluit, onKlaar }: Props) {
  const dialoog = useRef<HTMLDialogElement>(null);
  const hoofdknop = useRef<HTMLButtonElement>(null);
  const [pad, setPad] = useState(eerste);
  /** Wat de gebruiker in het naamveld tikte; null zolang hij er afblijft. */
  const [gewenst, setGewenst] = useState<string | null>(null);
  /** Mappen die de gebruiker aanwees om de video's in te zoeken. */
  const [zoek, setZoek] = useState<string[]>([]);
  const [kopie, setKopie] = useState<Kopie | null>(null);
  const [leest, setLeest] = useState(true);
  /** Het bestand is niet te lezen: kapot, vreemd, of van een nieuwere versie. */
  const [onleesbaar, setOnleesbaar] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  useEffect(() => {
    dialoog.current?.showModal();
  }, []);

  // Elke keer dat het bestand, de naam of de zoekmappen veranderen kijkt de
  // engine opnieuw: hij is de enige die weet welke naam vrij is en welke
  // video's er staan.
  useEffect(() => {
    let weg = false;
    setLeest(true);
    const id = setTimeout(
      () => {
        projectKopie(pad, gewenst, zoek)
          .then((k) => {
            if (weg) return;
            setKopie(k);
            setOnleesbaar(null);
            setLeest(false);
          })
          .catch((e) => {
            if (weg) return;
            setKopie(null);
            setOnleesbaar(schoon(e));
            setLeest(false);
          });
      },
      gewenst === null ? 0 : NAAM_WACHT_MS,
    );
    return () => {
      weg = true;
      clearTimeout(id);
    };
  }, [pad, gewenst, zoek]);

  // De focus hoort op de knop waarmee je verder gaat. `autoFocus` kan dat niet:
  // zolang de engine leest staat die knop uit, en een knop die uit staat krijgt
  // geen focus — dan valt hij op Annuleren en sluit Enter de dialoog. Het
  // naamveld blijft met rust: daar wordt getikt terwijl de engine meekijkt.
  useEffect(() => {
    if (leest || document.activeElement instanceof HTMLInputElement) return;
    hoofdknop.current?.focus();
  }, [leest]);

  async function anderBestand() {
    const keuze = await open({
      title: "Kopie van een project kiezen",
      multiple: false,
      directory: false,
      filters: [{ name: `${EDITIE.naam}-kopie`, extensions: ["zip"] }],
    });
    if (typeof keuze !== "string") return;
    setFout(null);
    setGewenst(null);
    setZoek([]);
    setPad(keuze);
  }

  async function wijsAan() {
    const map = await open({
      title: "In welke map staan de video's nu?",
      multiple: false,
      directory: true,
    });
    if (typeof map === "string" && !zoek.includes(map)) setZoek([...zoek, map]);
  }

  async function zetTerug() {
    if (kopie === null || leest || bezig) return;
    setFout(null);
    setBezig(true);
    try {
      onKlaar(await projectTerugzetten(pad, gewenst, zoek));
    } catch (e) {
      setFout(schoon(e));
      setBezig(false);
    }
  }

  const mis = kopie === null ? [] : ontbrekend(kopie);
  const bronnen = kopie === null ? null : bronnenTekst(kopie, zoek.length > 0);
  const uitleg = kopie === null ? null : naamUitleg(kopie, gewenst);

  return (
    <dialog
      ref={dialoog}
      className="verwijder terugzet"
      aria-labelledby="terugzet-kop"
      aria-busy={bezig || leest}
      onCancel={(e) => {
        // Esc sluit, behalve midden in het terugzetten.
        if (bezig) e.preventDefault();
      }}
      onClose={onSluit}
      onClick={(e) => {
        if (e.target === dialoog.current && !bezig) dialoog.current?.close();
      }}
    >
      <div className="verwijder-binnen">
        <header className="verwijder-kop">
          <span className="verwijder-teken" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9a6 6 0 1 0 1.9-4.4" />
              <path d="M3 2.6v3h3" />
              <path d="M9 6v3.2l2 1.3" />
            </svg>
          </span>
          <div>
            <h2 id="terugzet-kop">Kopie terugzetten</h2>
            <p>
              <span className="mono">{bestandsnaam(pad)}</span>
            </p>
          </div>
        </header>

        {kopie === null && onleesbaar === null && <p className="terugzet-leest">Kopie lezen…</p>}

        {onleesbaar !== null && (
          <p className="verwijder-fout" role="alert">
            {onleesbaar}
          </p>
        )}

        {kopie !== null && bronnen !== null && (
          <>
            <dl className="terugzet-feiten">
              <dt>Project</dt>
              <dd>
                <b>{kopie.project}</b>
                <span className="mono">
                  {" "}· {kopie.aantal_clips} {kopie.aantal_clips === 1 ? "clip" : "clips"}
                </span>
              </dd>
              <dt>Kopie gemaakt</dt>
              <dd>{datumTekst(kopie.gemaakt)}</dd>
              <dt>Zit erin</dt>
              <dd>
                {[kopie.heeft_montage ? "montage" : "nog geen montage", "analyse en keuzes", kopie.heeft_muziek ? "muziek" : null]
                  .filter(Boolean)
                  .join(", ")}
              </dd>
              <dt>Voorvertoningen</dt>
              <dd>
                {kopie.proxies
                  ? "Zitten erbij: je kunt meteen verder."
                  : `Zitten er niet bij. ${EDITIE.naam} maakt ze opnieuw uit je video's.`}
              </dd>
              <dt>Grootte</dt>
              <dd className="mono">{grootteTekst(kopie.bytes)}</dd>
            </dl>

            <label className="terugzet-naam">
              <span>Naam van het project</span>
              <input
                value={gewenst ?? kopie.naam}
                disabled={bezig}
                spellCheck={false}
                onChange={(e) => setGewenst(e.target.value)}
              />
              {uitleg !== null && <small data-bezet={kopie.bezet}>{uitleg}</small>}
            </label>

            {bronnen.toon === "ok" && (
              <p className="verwijder-gerust">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="8" cy="8" r="6.2" />
                  <path d="m5.4 8.2 1.8 1.8 3.4-3.8" />
                </svg>
                <span>
                  <b>{bronnen.kop}</b> {bronnen.uitleg}
                </span>
              </p>
            )}
            {bronnen.toon === "let-op" && (
              <div className="verwijder-loopt terugzet-mist" role="status">
                <span>
                  <b>{bronnen.kop}</b> {bronnen.uitleg}
                </span>
                <ul>
                  {mis.slice(0, TOON_ONTBREKEND).map((b) => (
                    <li key={b.naam}>
                      <span className="mono">{b.naam}</span>
                      <span className="mono maat">{grootteTekst(b.bytes)}</span>
                    </li>
                  ))}
                  {mis.length > TOON_ONTBREKEND && (
                    <li>
                      <span>en nog {mis.length - TOON_ONTBREKEND}</span>
                    </li>
                  )}
                </ul>
                <button type="button" className="knop" disabled={bezig || leest} onClick={() => void wijsAan()}>
                  {zoek.length > 0 ? "Nog een map aanwijzen…" : "Map aanwijzen…"}
                </button>
              </div>
            )}
          </>
        )}

        {fout !== null && (
          <p className="verwijder-fout" role="alert">
            {fout}
          </p>
        )}

        <footer className="verwijder-knoppen">
          <button type="button" className="knop" disabled={bezig} onClick={() => dialoog.current?.close()}>
            Annuleren
          </button>
          {onleesbaar !== null ? (
            <button ref={hoofdknop} type="button" className="knop-primair" onClick={() => void anderBestand()}>
              Ander bestand kiezen…
            </button>
          ) : (
            <button
              ref={hoofdknop}
              type="button"
              className="knop-primair"
              disabled={kopie === null || leest || bezig}
              onClick={() => void zetTerug()}
            >
              {bezig ? "Bezig…" : mis.length > 0 ? "Toch terugzetten" : "Terugzetten"}
            </button>
          )}
        </footer>
      </div>
    </dialog>
  );
}
