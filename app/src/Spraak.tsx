// De spraakkaart in stap 4: ondertitels aan of uit.
//
// Aanzetten laat de engine de clips in de montage transcriberen (whisper.cpp,
// lokaal), legt de ondertitels als laag op de montage en zet het eigen geluid
// aan op elk shot waarin gepraat wordt — de muziek duikt daar vanzelf onder.
// Alles blijft staan bij "opnieuw regisseren"; zie engine/cve/spraak.py.
//
// Staat het spraakmodel nog niet op deze computer, dan haalt de kaart het op
// (spraakinstall.py, 15-10-2026). Tot die dag zei hij alleen "staat niet op
// deze computer", zonder uitweg.
import { useEffect, useState, type CSSProperties } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  GEBEURTENIS,
  spraakInstalleer,
  spraakInstalleerStop,
  spraakMaak,
  spraakStand,
  spraakWeg,
  type Spraakstand,
} from "./engine";
import { bytesTekst } from "./format";
import { EDITIE } from "./editie";

type Props = {
  project: string;
  /** Mag de app internet op? Het model moet één keer binnenkomen. */
  online?: boolean;
  /** Na klaar: de montage is veranderd (overlay, geluid) en moet opnieuw opgehaald. */
  onVeranderd: () => void;
};

type Gebeurtenis = {
  gebeurtenis: "voortgang" | "klaar" | "fout";
  data: {
    werk?: string;
    project?: string;
    tekst?: string;
    fout?: string;
    woorden?: number;
    gedaan?: number;
    totaal?: number;
    gestopt?: boolean;
  };
};

export default function Spraak({ project, online = true, onVeranderd }: Props) {
  const [stand, setStand] = useState<Spraakstand | null>(null);
  const [bezig, setBezig] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [ophalen, setOphalen] = useState<{ gedaan: number; totaal: number } | null>(null);

  useEffect(() => {
    let geldig = true;
    setStand(null);
    spraakStand(project)
      .then((s) => {
        if (!geldig) return;
        setStand(s);
        if (s.installeren_bezig) setOphalen({ gedaan: 0, totaal: s.model_bytes ?? 0 });
      })
      .catch((e) => geldig && setFout(String(e)));
    return () => {
      geldig = false;
    };
  }, [project]);

  useEffect(() => {
    const stop = listen<Gebeurtenis>(GEBEURTENIS, ({ payload }) => {
      const d = payload.data;
      if (d.werk === "spraakinstall") {
        if (payload.gebeurtenis === "voortgang") {
          setOphalen({ gedaan: d.gedaan ?? 0, totaal: d.totaal ?? 0 });
        } else {
          setOphalen(null);
          if (payload.gebeurtenis === "fout") setFout(d.fout ?? "Het ophalen is mislukt.");
          spraakStand(project).then(setStand).catch(() => {});
        }
        return;
      }
      if (d.werk !== "spraak" || d.project !== project) return;
      if (payload.gebeurtenis === "voortgang") {
        setBezig(d.tekst ?? "Spraak herkennen…");
      } else if (payload.gebeurtenis === "fout") {
        setBezig(null);
        setFout(d.fout ?? "Het herkennen is mislukt.");
      } else {
        setBezig(null);
        spraakStand(project).then(setStand).catch(() => {});
        onVeranderd();
      }
    });
    return () => {
      void stop.then((f) => f());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  async function schakel() {
    if (!stand) return;
    setFout(null);
    try {
      if (stand.aan) {
        setStand(await spraakWeg(project));
        onVeranderd();
      } else {
        setBezig("Spraak herkennen…");
        await spraakMaak(project);
      }
    } catch (e) {
      setBezig(null);
      setFout(String(e));
    }
  }

  async function haalModel() {
    setFout(null);
    try {
      setOphalen({ gedaan: 0, totaal: stand?.model_bytes ?? 0 });
      await spraakInstalleer();
    } catch (e) {
      setOphalen(null);
      setFout(String(e));
    }
  }

  if (stand === null && fout === null) return null;
  const aan = stand?.aan ?? false;
  const deel = ophalen && ophalen.totaal > 0 ? Math.min(1, ophalen.gedaan / ophalen.totaal) : 0;
  return (
    <div className="groep spraak">
      <span className="kop-klein">Spraak en ondertitels</span>
      <button
        className="schakelaar"
        role="switch"
        aria-checked={aan}
        disabled={bezig !== null || ophalen !== null || !stand?.kan}
        onClick={() => void schakel()}
      >
        <span>{bezig !== null ? "Bezig…" : aan ? "Ondertitels aan" : "Ondertitels uit"}</span>
        <span className="wip" />
      </button>
      {ophalen !== null ? (
        <>
          <div
            className="voortgangsbalk"
            role="progressbar"
            aria-valuenow={Math.round(deel * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {/* Een div, geen span: een inline-element heeft geen hoogte en
                dan bleef de balk leeg (gezien in spraakmodel.mjs). */}
            <div
              className={`vulling${ophalen.gedaan === 0 ? " pendelt" : ""}`}
              style={{ "--deel": deel } as CSSProperties}
            />
          </div>
          <span className="kleine-noot" role="status">
            Spraakmodel ophalen… {bytesTekst(ophalen.gedaan)} van {bytesTekst(ophalen.totaal)}
          </span>
          <button className="knop" onClick={() => void spraakInstalleerStop()}>
            Annuleren
          </button>
        </>
      ) : bezig !== null ? (
        <span className="kleine-noot" role="status">{bezig}</span>
      ) : aan ? (
        <span className="kleine-noot">
          {stand?.woorden ?? 0} woorden in {stand?.regels ?? 0} regels. Waar gepraat wordt hoor je
          de clip en duikt de muziek eronder.
        </span>
      ) : stand?.kan ? (
        <span className="kleine-noot">
          Herkent wat er gezegd wordt (lokaal), zet het in beeld en laat de clip daar horen.
        </span>
      ) : stand?.model_ophaalbaar ? (
        <>
          <span className="kleine-noot">
            Voor ondertitels haalt {EDITIE.naam} één keer een spraakmodel op (
            {bytesTekst(stand.model_bytes ?? 0)}). Daarna werkt het zonder internet.
          </span>
          <button className="knop-primair" disabled={!online} onClick={() => void haalModel()}>
            Spraakmodel ophalen
          </button>
          {!online && (
            <span className="kleine-noot">Zet de schakelaar rechtsboven op Online om het op te halen.</span>
          )}
        </>
      ) : (
        <span className="kleine-noot">Spraakherkenning staat niet op deze computer.</span>
      )}
      {fout && <span className="kleine-noot mono">{fout}</span>}
    </div>
  );
}
