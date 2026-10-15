// De dialoog waarmee je een project weghaalt. Drie beloftes staan erin, in
// woorden die geen uitleg nodig hebben: je eigen video's blijven staan, alles
// gaat naar de prullenbak, en wat je wilt houden blijft bewaard.
//
// Een native <dialog>: Esc, de focusval en de laag boven alles komen van de
// browser, niet van ons.
import { useEffect, useRef, useState } from "react";
import { save } from "@tauri-apps/plugin-dialog";
import { projectOmvang, projectVerwijder, type Verwijderd } from "./engine";
import {
  KEUZESOORTEN,
  SOORT_TEKST,
  STANDAARD,
  blijft,
  gaatWeg,
  grootteTekst,
  kopieGrootte,
  kopieNaam,
  kruimelpad,
  wegLijst,
  type Keuze,
  type Omvang,
} from "./verwijderkeuze";
import { EDITIE } from "./editie";

/** Zolang het project bezig is: om de zoveel tijd opnieuw vragen, zodat de
 *  knop vanzelf vrijkomt als de render klaar is. */
const OPNIEUW_KIJKEN_MS = 2000;

type Props = {
  project: string;
  onSluit: () => void;
  /** Het project is weg. Vóór de engine begint roept de dialoog `onStart`
   *  aan: het open project moet eerst dicht, anders houdt de speler nog een
   *  bestand vast dat op Windows dan niet verplaatst kan worden. */
  onStart: () => void;
  onKlaar: (uit: Verwijderd) => void;
};

export default function VerwijderDialoog({ project, onSluit, onStart, onKlaar }: Props) {
  const dialoog = useRef<HTMLDialogElement>(null);
  const [omvang, setOmvang] = useState<Omvang | null>(null);
  const [keuze, setKeuze] = useState<Keuze>(STANDAARD);
  const [kopie, setKopie] = useState(false);
  const [metProxies, setMetProxies] = useState(false);
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  useEffect(() => {
    dialoog.current?.showModal();
  }, []);

  // Meten bij het openen, en blijven kijken zolang het project nog werkt.
  const loopt = omvang?.bezig ?? null;
  useEffect(() => {
    let weg = false;
    const haal = () =>
      projectOmvang(project)
        .then((o) => !weg && setOmvang(o))
        .catch((e) => !weg && setFout(String(e)));
    if (omvang === null) {
      void haal();
      return () => {
        weg = true;
      };
    }
    if (loopt === null) return;
    const id = setInterval(haal, OPNIEUW_KIJKEN_MS);
    return () => {
      weg = true;
      clearInterval(id);
    };
  }, [project, omvang === null, loopt]);

  async function verwijder() {
    if (omvang === null || bezig) return;
    setFout(null);
    let doel: string | null = null;
    if (kopie) {
      doel = await save({
        title: "Kopie van het project opslaan",
        defaultPath: kopieNaam(project),
        filters: [{ name: `${EDITIE.naam}-kopie`, extensions: ["zip"] }],
      });
      // Geen plek gekozen is geen toestemming om zonder kopie door te gaan.
      if (doel === null) return;
    }
    setBezig(true);
    onStart();
    try {
      onKlaar(await projectVerwijder(project, wegLijst(keuze), doel, kopie && metProxies));
    } catch (e) {
      setFout(String(e).replace(/^Error: /, ""));
      setBezig(false);
    }
  }

  const weg = omvang === null ? 0 : gaatWeg(omvang, keuze);
  const houd = omvang === null ? 0 : blijft(omvang, keuze);
  const zichtbaar = omvang === null ? [] : KEUZESOORTEN.filter((s) => omvang.soorten[s].bestanden > 0);
  const magWeg = omvang !== null && loopt === null && !bezig;

  return (
    <dialog
      ref={dialoog}
      className="verwijder"
      aria-labelledby="verwijder-kop"
      aria-busy={bezig}
      onCancel={(e) => {
        // Esc sluit, behalve midden in het verplaatsen.
        if (bezig) e.preventDefault();
      }}
      onClose={onSluit}
      onClick={(e) => {
        // Een klik naast het venster is een klik op de <dialog> zelf.
        if (e.target === dialoog.current && !bezig) dialoog.current?.close();
      }}
    >
      <div className="verwijder-binnen">
        <header className="verwijder-kop">
          <span className="verwijder-teken" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 4.5h12M7 4.5V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M4.5 4.5l.6 9.6a1.5 1.5 0 0 0 1.5 1.4h4.8a1.5 1.5 0 0 0 1.5-1.4l.6-9.6M7.5 7.5v5M10.5 7.5v5" />
            </svg>
          </span>
          <div>
            <h2 id="verwijder-kop">Project verwijderen</h2>
            <p>
              <b>{project}</b>
              {omvang !== null && (
                <span className="mono">
                  {" "}· {omvang.aantal_clips} {omvang.aantal_clips === 1 ? "clip" : "clips"} ·{" "}
                  {grootteTekst(omvang.totaal)} op deze computer
                </span>
              )}
            </p>
          </div>
        </header>

        <p className="verwijder-gerust">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 1.5 2.5 3.5v4.2c0 3.2 2.2 5.6 5.5 6.8 3.3-1.2 5.5-3.6 5.5-6.8V3.5L8 1.5Z" />
            <path d="m5.8 8 1.6 1.6 2.9-3.2" />
          </svg>
          <span>
            <b>Je eigen video's blijven waar ze zijn.</b> {EDITIE.naam} haalt alleen weg wat het zelf heeft
            gemaakt of gekopieerd — nooit de originelen op je camera, telefoon of schijf.
          </span>
        </p>

        {loopt !== null && (
          <p className="verwijder-loopt" role="status">
            Dit project is nog bezig: <b>{loopt}</b>. Verwijderen kan zodra dat klaar is.
          </p>
        )}

        <fieldset disabled={bezig || omvang === null}>
          <legend>Eerst bewaren</legend>
          <label className="vinkrij">
            <input type="checkbox" checked={kopie} onChange={(e) => setKopie(e.target.checked)} />
            <span className="vinkrij-tekst">
              <b>Kopie van het project opslaan</b>
              <small>
                Montage, analyse, keuzes en muziek in één .zip-bestand. Jij kiest waar — daarmee
                haal je het project later terug.
              </small>
            </span>
            <span className="mono vinkrij-maat">
              {omvang === null ? "…" : grootteTekst(kopieGrootte(omvang, kopie && metProxies))}
            </span>
          </label>
          {kopie && omvang !== null && omvang.kopie.proxies > 0 && (
            <label className="vinkrij inspring">
              <input
                type="checkbox"
                checked={metProxies}
                onChange={(e) => setMetProxies(e.target.checked)}
              />
              <span className="vinkrij-tekst">
                <b>Ook de voorvertoningen</b>
                <small>Dan kun je na het terugzetten meteen verder, zonder opnieuw in te lezen.</small>
              </span>
              <span className="mono vinkrij-maat">+ {grootteTekst(omvang.kopie.proxies)}</span>
            </label>
          )}
        </fieldset>

        <fieldset disabled={bezig || omvang === null}>
          <legend>Wat gaat er weg</legend>
          <label className="vinkrij vast">
            <input type="checkbox" checked readOnly disabled />
            <span className="vinkrij-tekst">
              <b>{SOORT_TEKST.werk.titel}</b>
              <small>{SOORT_TEKST.werk.uitleg}</small>
            </span>
            <span className="mono vinkrij-maat">
              {omvang === null ? "…" : grootteTekst(omvang.soorten.werk.bytes)}
            </span>
          </label>
          {zichtbaar.map((s) => (
            <label key={s} className="vinkrij" data-houd={!keuze[s]}>
              <input
                type="checkbox"
                checked={keuze[s]}
                onChange={(e) => setKeuze({ ...keuze, [s]: e.target.checked })}
              />
              <span className="vinkrij-tekst">
                <b>{SOORT_TEKST[s].titel}</b>
                <small>{keuze[s] ? SOORT_TEKST[s].uitleg : "Blijft bewaard."}</small>
              </span>
              <span className="mono vinkrij-maat">{grootteTekst(omvang!.soorten[s].bytes)}</span>
            </label>
          ))}
        </fieldset>

        {omvang !== null && (
          <div className="verwijder-som">
            <div className="verwijder-balk" aria-hidden="true">
              <span className="weg" style={{ flexGrow: weg }} />
              {houd > 0 && <span className="houd" style={{ flexGrow: houd }} />}
            </div>
            <p>
              <span className="weg">
                <b className="mono">{grootteTekst(weg)}</b> naar de {omvang.prullenbak}
              </span>
              {houd > 0 && (
                <span className="houd">
                  <b className="mono">{grootteTekst(houd)}</b> blijft bewaard
                </span>
              )}
            </p>
            <p className="verwijder-noot">
              Niets gaat definitief weg: een vergissing haal je terug uit de {omvang.prullenbak}.
              {houd > 0 && <> Wat je houdt staat daarna in {kruimelpad(omvang.bewaard)}.</>}
            </p>
          </div>
        )}

        {fout !== null && (
          <p className="verwijder-fout" role="alert">
            {fout}
          </p>
        )}

        <footer className="verwijder-knoppen">
          <button
            type="button"
            className="knop"
            autoFocus
            disabled={bezig}
            onClick={() => dialoog.current?.close()}
          >
            Annuleren
          </button>
          <button type="button" className="knop-gevaar" disabled={!magWeg} onClick={() => void verwijder()}>
            {bezig ? (
              "Bezig…"
            ) : (
              <>
                Project verwijderen
                {omvang !== null && <span className="mono"> · {grootteTekst(weg)}</span>}
              </>
            )}
          </button>
        </footer>
      </div>
    </dialog>
  );
}
