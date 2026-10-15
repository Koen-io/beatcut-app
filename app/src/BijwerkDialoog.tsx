// De pop-up van het bijwerken: één kaart met een ring die de fase laat zien.
// Draait tijdens het zoeken, valt dicht tot een vinkje (bij) of een pijl
// (nieuw), en wordt tijdens het ophalen de voortgangsbalk. Zie
// `bijwerkstand.ts` voor wanneer hij in beeld staat en `styles.css`
// ("bijwerken: de pop-up") voor de beweging.
import { useEffect, useState } from "react";

import { AFTEL_MS, deel } from "./bijwerkstand";
import { EDITIE } from "./editie";
import { bytesTekst } from "./format";
import type { Bijwerken } from "./zelf-bijwerken";

type Props = { b: Bijwerken };

export default function BijwerkDialoog({ b }: Props) {
  const { fase } = b;
  const [uit, setUit] = useState(false);
  // Wegvallen laten zien voor hij echt weg is.
  useEffect(() => {
    if (b.zichtbaar) setUit(false);
  }, [b.zichtbaar]);
  if (!b.zichtbaar && !uit) return null;

  const sluit = () => {
    setUit(true);
    setTimeout(() => {
      b.verberg();
      setUit(false);
    }, 220);
  };

  return (
    <div className={`bijwerk-sluier${uit || !b.zichtbaar ? " uit" : ""}`} role="dialog" aria-modal="true" aria-label="Updates">
      <div className="bijwerk-kaart" style={{ "--aftel": `${AFTEL_MS}ms` } as React.CSSProperties}>
        {fase.soort !== "haalt" && (
          <button className="sluit" onClick={sluit} aria-label="Sluiten">×</button>
        )}
        <Ring fase={fase} />
        <Inhoud b={b} sluit={sluit} />
        {fase.soort === "bij" && (
          <div className="aftel" aria-hidden="true"><i /></div>
        )}
      </div>
    </div>
  );
}

function Ring({ fase }: { fase: Bijwerken["fase"] }) {
  const d = fase.soort === "haalt" ? deel(fase.ontvangen, fase.totaal) : null;
  const klasse =
    fase.soort === "zoekt" ? "zoekt"
    : fase.soort === "bij" ? "bij"
    : fase.soort === "nieuw" ? "nieuw"
    : fase.soort === "haalt" ? "haalt"
    : fase.soort === "klaar" ? "bij"
    : fase.soort === "fout" ? "fout"
    : "";
  const omtrek = 251.3;
  const offset =
    fase.soort === "haalt" ? omtrek * (1 - (d ?? 0))
    : fase.soort === "zoekt" ? 190
    : 0;
  return (
    <div className={`bijwerk-ring ${klasse}`} aria-hidden="true">
      <svg viewBox="0 0 88 88">
        <circle className="spoor" cx="44" cy="44" r="40" />
        <circle className="loop" cx="44" cy="44" r="40" style={{ strokeDashoffset: offset }} />
      </svg>
      {fase.soort === "haalt" ? (
        <span className="procent">{d === null ? "…" : `${Math.round(d * 100)}%`}</span>
      ) : (
        <span className="teken">
          {(fase.soort === "bij" || fase.soort === "klaar") && (
            <svg viewBox="0 0 36 36"><path d="M10 18.5l5.5 5.5L26 13" /></svg>
          )}
          {fase.soort === "nieuw" && (
            <svg viewBox="0 0 36 36"><path d="M18 9v16M11 18.5L18 25.5l7-7" /></svg>
          )}
          {fase.soort === "fout" && (
            <svg viewBox="0 0 36 36"><path d="M18 10v10M18 24.5v1.5" /></svg>
          )}
        </span>
      )}
    </div>
  );
}

function Inhoud({ b, sluit }: { b: Bijwerken; sluit: () => void }) {
  const { fase } = b;
  switch (fase.soort) {
    case "zoekt":
      return (
        <>
          <h2>Controleren op updates…</h2>
          <p className="uitleg">Even kijken of er een nieuwere {EDITIE.naam} is.</p>
        </>
      );
    case "bij":
      return (
        <>
          <h2>Je bent helemaal bij</h2>
          <div className="versie">{EDITIE.naam} <b>{fase.huidige}</b> is de nieuwste versie.</div>
        </>
      );
    case "nieuw":
      return (
        <>
          <h2>Er is een nieuwe versie</h2>
          <div className="versie">
            <b>{fase.controle.versie}</b> staat klaar — je hebt {fase.controle.huidige}
            {fase.controle.datum !== null && ` · ${datumTekst(fase.controle.datum)}`}
          </div>
          {fase.controle.notities !== null && fase.controle.notities.trim() !== "" && (
            <pre className="notities">{fase.controle.notities.trim()}</pre>
          )}
          <div className="knoppen">
            <button className="knop" onClick={sluit}>Later</button>
            <button className="knop-nadruk" onClick={b.ophalen}>Nu ophalen</button>
          </div>
          <div className="voet">Ophalen gebeurt op de achtergrond; installeren pas als jij herstart.</div>
        </>
      );
    case "haalt":
      return (
        <>
          <h2>Ophalen…</h2>
          <div className="versie">
            {EDITIE.naam} <b>{fase.controle.versie}</b>
            {fase.totaal !== null && ` · ${bytesTekst(fase.ontvangen)} van ${bytesTekst(fase.totaal)}`}
          </div>
          <p className="uitleg">Je kunt intussen gewoon doorwerken. De handtekening wordt gecontroleerd voordat er iets geïnstalleerd wordt.</p>
        </>
      );
    case "klaar":
      return (
        <>
          <h2>{EDITIE.naam} {fase.controle.versie} staat klaar</h2>
          <p className="uitleg">
            {b.magHerstarten
              ? "Opgehaald en gecontroleerd. Hij wordt geïnstalleerd zodra je herstart."
              : `Opgehaald en gecontroleerd. Er loopt nog werk (${b.bezigMet}) — herstarten kan zodra dat klaar is.`}
          </p>
          <div className="knoppen">
            <button className="knop" onClick={sluit}>Later</button>
            <button
              className="knop-nadruk"
              onClick={b.herstart}
              disabled={!b.magHerstarten}
              title={b.magHerstarten ? undefined : `Nu niet: ${b.bezigMet}`}
            >
              Nu herstarten
            </button>
          </div>
        </>
      );
    case "fout":
      return (
        <>
          <h2>Controleren lukte niet</h2>
          <p className="uitleg">{fase.bericht}</p>
          <div className="knoppen">
            <button className="knop" onClick={sluit}>Sluiten</button>
            <button className="knop-licht" onClick={b.controleer}>Opnieuw proberen</button>
          </div>
        </>
      );
    default:
      return null;
  }
}

function datumTekst(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" });
}
