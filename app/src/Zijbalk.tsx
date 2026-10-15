// Een kolom met een sleepgreep ernaast. Alle zeven zijbalken in de app gaan
// hierdoorheen, zodat ze allemaal dezelfde greep, dezelfde grenzen en hetzelfde
// gedrag hebben: slepen, dubbelklik terug naar standaard, pijltjestoetsen, en
// de breedte blijft bewaard tussen starts.
//
// De greep is géén kind van de `<aside>`. Die heeft `overflow-y: auto` voor
// lange lijsten, en dat klipt een kind dat over de rand heen moet steken. Hij
// is dus een broertje in dezelfde flexrij, met negatieve marges zodat hij
// precies op de scheidslijn ligt zonder ruimte in te nemen.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { breedteGrenzen, lees, nieuweBreedte, schrijf, STAP, type Kant } from "./kolombreedte";

type Props = {
  /** Aan welke kant van het midden deze kolom staat. Bepaalt waar de greep
   *  komt en welke pijltjestoets breder maakt. */
  kant: Kant;
  /** Waar de breedte onthouden wordt. Eén sleutel per kolom, want de lijst in
   *  stap 2 en het paneel in stap 4 hebben niets met elkaar te maken. */
  sleutel: string;
  /** De breedte uit het ontwerp, en waar dubbelklikken naar terugzet. */
  standaard: number;
  /** Voor de schermlezer: welke kolom versleept wordt. */
  naam: string;
  klasse?: string;
  children: ReactNode;
};

export default function Zijbalk({ kant, sleutel, standaard, naam, klasse = "", children }: Props) {
  const [breedte, setBreedte] = useState(() => lees(sleutel, standaard));
  const [sleept, setSleept] = useState(false);
  const balk = useRef<HTMLElement | null>(null);
  // De laatste breedte, buiten React om. De gebeurtenisafhandelaars zien
  // `breedte` zoals die was toen ze gemaakt werden, en React tekent niet bij
  // elke muisbeweging opnieuw: bij het loslaten na een snelle sleep bewaarde
  // de oude code daardoor 305 px terwijl de kolom op 323 px stond (gemeten
  // 04-10-2026 in de QA-brug).
  const nu = useRef(breedte);

  const [min, max] = breedteGrenzen(standaard);

  /** Zetten én bewaren. `bewaar` staat uit tijdens het slepen: dat zou bij elke
   *  muisbeweging naar schijf schrijven. */
  const zet = useCallback(
    (px: number, bewaar: boolean) => {
      const nieuw = Math.round(Math.min(max, Math.max(min, px)));
      nu.current = nieuw;
      setBreedte(nieuw);
      if (bewaar) schrijf(sleutel, nieuw);
    },
    [sleutel, min, max],
  );

  // Het venster kan kleiner worden dan waar de breedte op stond — bij twee
  // kolommen van 420 px op een smal venster blijft er niets van het midden
  // over. De bovengrens hangt daarom aan de venstergrootte; dit haalt een
  // bewaarde breedte daar weer binnen.
  useEffect(() => {
    const pas = () =>
      setBreedte((b) => {
        const geklemd = Math.min(breedteGrenzen(standaard)[1], Math.max(min, b));
        nu.current = geklemd;
        return geklemd;
      });
    pas();
    window.addEventListener("resize", pas);
    return () => window.removeEventListener("resize", pas);
  }, [standaard, min]);

  function uitPositie(x: number): number {
    const r = balk.current?.getBoundingClientRect();
    if (r === undefined) return breedte;
    return kant === "links" ? x - r.left : r.right - x;
  }

  const greep = (
    <button
      type="button"
      className={`greep ${kant}${sleept ? " sleept" : ""}`}
      // De standaardrol voor een scheiding die je kunt verslepen. Een knop
      // zonder deze rol kondigt een schermlezer aan als "knop", en dan is er
      // geen enkele aanwijzing dat er iets te verslepen valt.
      role="separator"
      aria-orientation="vertical"
      aria-label={`Breedte van ${naam}`}
      aria-valuenow={breedte}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={(e) => {
        // Vangen mag mislukken — een aanraking die al weg is, of een
        // nagebootste gebeurtenis zonder echte pointer. Dat mag geen
        // onafgevangen fout in de console worden.
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          /* dan werkt het slepen zolang de muis boven de greep blijft */
        }
        setSleept(true);
      }}
      onPointerMove={(e) => {
        if (sleept) zet(uitPositie(e.clientX), false);
      }}
      onPointerUp={(e) => {
        try {
          e.currentTarget.releasePointerCapture(e.pointerId);
        } catch {
          /* al los */
        }
        setSleept(false);
        schrijf(sleutel, nu.current);
      }}
      onPointerCancel={() => {
        setSleept(false);
        schrijf(sleutel, nu.current);
      }}
      onDoubleClick={() => zet(standaard, true)}
      onKeyDown={(e) => {
        const volgende = nieuweBreedte(e.key, e.shiftKey, breedte, standaard, kant);
        if (volgende === null) return;
        e.preventDefault();
        zet(volgende, true);
      }}
      // Zonder titel is een strookje van elf pixels een raadsel; dit is de
      // enige plek waar het gedrag te ontdekken valt.
      title={`Versleep om ${naam} breder of smaller te maken · dubbelklik voor ${standaard} px · pijltjestoetsen per ${STAP} px`}
    />
  );

  return (
    <>
      {kant === "rechts" && greep}
      <aside ref={balk} className={`zijbalk ${klasse}`.trim()} style={{ width: breedte }}>
        {children}
      </aside>
      {kant === "links" && greep}
    </>
  );
}
