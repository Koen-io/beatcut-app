// Het instellingenpaneel: over de app, updates, de engine en de licenties.
// Dit is de plek voor "Controleren op updates" — naast de versie die je
// hebt en wanneer er voor het laatst gekeken is, zodat de knop context heeft
// en niet ergens los in een menu hangt.
import { useState } from "react";

import { laatstTekst } from "./bijwerkstand";
import { EDITIE, LOGO_URL } from "./editie";
import { engine, type Check, type Doctor, type Hallo } from "./engine";
import type { Bijwerken } from "./zelf-bijwerken";

export type EngineStand =
  | { soort: "laden" }
  | { soort: "klaar"; hallo: Hallo; doctor: Doctor }
  | { soort: "fout"; bericht: string };

type Props = {
  b: Bijwerken;
  stand: EngineStand;
  webgpu: Check | null;
  online: boolean;
  versie: string;
};

export default function Instellingen({ b, stand, webgpu, online, versie }: Props) {
  const [licenties, setLicenties] = useState<string | null>(null);
  const zoekt = b.fase.soort === "zoekt" || b.fase.soort === "haalt";

  return (
    <div className="paneel instellingen" role="dialog" aria-label="Instellingen">
      <div className="kop">
        {LOGO_URL !== null ? <img src={LOGO_URL} alt="" draggable={false} /> : <Balkjes />}
        <div className="naam">
          <b>{EDITIE.naam} {versie}</b>
          {EDITIE.motto !== null ? <span className="motto">{EDITIE.motto}</span> : <span>{EDITIE.ondertitel}</span>}
        </div>
      </div>

      <div className="inhoud">
        <section>
          <h3>Updates</h3>
          <div className="rij">
            <div className="links">
              <Updatestand b={b} versie={versie} />
              <span>{laatstTekst(b.laatst)}{!online && " · je staat op Offline"}</span>
            </div>
            <div className="knop-rij-rechts" style={{ marginTop: 0 }}>
              {b.fase.soort === "klaar" ? (
                <button className="knop-licht" onClick={b.toon}>Nu herstarten…</button>
              ) : b.fase.soort === "nieuw" ? (
                <button className="knop-licht" onClick={b.toon}>Ophalen…</button>
              ) : (
                <button className="knop" onClick={b.controleer} disabled={zoekt}>
                  {zoekt ? "Bezig…" : "Controleren op updates"}
                </button>
              )}
            </div>
          </div>
          <div className="rij">
            <div className="links">
              Automatisch controleren
              <span>Bij het openen en daarna elke 4 uur. Installeren gebeurt nooit zonder jouw klik.</span>
            </div>
            <span className="waarde">aan</span>
          </div>
        </section>

        <section>
          <h3>Engine</h3>
          {stand.soort === "laden" && <p className="paneel-uitleg">De engine wordt gestart…</p>}
          {stand.soort === "fout" && (
            <>
              <p className="paneel-uitleg">Engine niet bereikbaar</p>
              <p className="mono">{stand.bericht}</p>
            </>
          )}
          {stand.soort === "klaar" && (
            <>
              <p className="paneel-uitleg">
                Engine {stand.hallo.versie} · protocol {stand.hallo.protocol} ·{" "}
                {stand.doctor.ok ? "alles in orde" : `${stand.doctor.fouten} probleem/problemen`}
              </p>
              {[...stand.doctor.checks, ...(webgpu ? [webgpu] : [])].map((c) => (
                <div className="check" key={c.naam}>
                  <span className={`dot ${c.ok ? "ok" : c.vereist ? "fout" : ""}`} style={{ marginTop: 5 }} />
                  <span>{c.naam}</span>
                  <span className="detail" title={c.detail}>{c.detail}</span>
                </div>
              ))}
              {stand.hallo.projecten !== undefined && (
                <div className="rij">
                  <div className="links">
                    Projecten
                    <span className="mono" title={stand.hallo.projecten}>{stand.hallo.projecten}</span>
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        <section>
          <h3>Over</h3>
          <div className="rij">
            <div className="links">
              Licenties van derden
              <span>ffmpeg (LGPL), whisper.cpp, de lettertypes en de rest.</span>
            </div>
            <button
              className="knop-klein-rand"
              onClick={() => {
                if (licenties !== null) return setLicenties(null);
                engine<{ tekst: string }>("licenties")
                  .then((r) => setLicenties(r.tekst))
                  .catch((e) => setLicenties(String(e)));
              }}
            >
              {licenties === null ? "Tonen" : "Verbergen"}
            </button>
          </div>
          {licenties !== null && <pre className="licenties">{licenties}</pre>}
        </section>
      </div>
    </div>
  );
}

function Updatestand({ b, versie }: { b: Bijwerken; versie: string }) {
  switch (b.fase.soort) {
    case "zoekt":
      return <span className="stand"><span className="dot bezig" /> Controleren…</span>;
    case "haalt":
      return <span className="stand nieuw"><span className="dot bezig" /> {b.fase.controle.versie} wordt opgehaald</span>;
    case "nieuw":
      return <span className="stand nieuw"><span className="dot" style={{ background: "var(--nadruk)" }} /> Versie {b.fase.controle.versie} beschikbaar</span>;
    case "klaar":
      return <span className="stand nieuw"><span className="dot" style={{ background: "var(--nadruk)" }} /> Versie {b.fase.controle.versie} staat klaar</span>;
    case "bij":
      return <span className="stand bij"><span className="dot ok" /> Je bent bij ({versie})</span>;
    case "fout":
      return <span className="stand"><span className="dot fout" /> {b.fase.bericht}</span>;
    default:
      return <span className="stand">Versie {versie}</span>;
  }
}

function Balkjes() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="#16191F" />
      <rect x="5" y="10" width="2" height="4" rx="1" fill="var(--accent)" />
      <rect x="8.5" y="7" width="2" height="10" rx="1" fill="var(--accent)" />
      <rect x="12" y="5" width="2" height="14" rx="1" fill="#F3F4F6" />
      <rect x="15.5" y="8" width="2" height="8" rx="1" fill="var(--accent)" />
      <rect x="19" y="10.5" width="2" height="3" rx="1" fill="var(--accent)" />
    </svg>
  );
}
