// De titels live over de voorvertoning, uit hetzelfde sjabloon als de export.
//
// De render maakt per titel een transparante MOV met HyperFrames (zie
// `graphics.render_overlay`). Dat kost een browserrender per titel en kan dus
// niet meelopen met de klok. In plaats daarvan draait hier dezelfde compositie:
// dezelfde HTML, dezelfde CSS, dezelfde GSAP-tijdlijn en dezelfde variabelen
// uit `edl.json` — alleen wordt de tijdlijn op de klok gezet (`tl.time()`) in
// plaats van frame voor frame uitgerenderd.
//
// Vier dingen die hier bewust zo zijn:
//
// 1. **De compositie draait in het app-document, niet in een iframe.** Een
//    iframe zou de sjabloonbestanden van schijf moeten halen; het
//    asset-protocol van Tauri komt alleen bij de projectmap, en een `srcdoc`
//    met inline scripts valt onder de CSP van de app. In het app-document is
//    alles al gebundeld en hoeft er niets versoepeld te worden.
// 2. **`titel20.js` zoekt `#root`.** Daarom heet het wortelelement van de app
//    zelf `#app` (zie `index.html`): twee elementen met hetzelfde id zou de
//    compositie de hele interface laten vullen.
// 3. **Het sjabloon rekent met de canvasmaat uit de EDL** (1920×1080), net als
//    de render. De laag wordt daarna als geheel geschaald naar de maat van het
//    canvas, zodat elke letter op precies dezelfde plek staat als in de export.
// 4. **Overlappende titels staan er allemaal**, elk in een eigen vak met een
//    eigen tijdlijn, in de volgorde van `edl.json` — dezelfde stapeling die
//    `render._overlays_erover()` in de export maakt. Dat kan alleen door ze één
//    voor één op te bouwen: `titel20.js` praat met het document zelf
//    (`getElementById('root')`, de gsap-selectors `#kaart`/`#balk`, en
//    `window.__timelines.titel20`). Een vak dat klaar is geeft daarom zijn
//    id's weer vrij; de vormgeving hangt aan de classes ernaast, zodat het
//    daar niets van merkt (`brands/sjablonen/titel20.css`).
import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { projectTitels, type Titelweb } from "../engine";
// Het sjabloon zelf. Eén bron voor render én voorvertoning: deze drie
// bestanden zijn dezelfde die `graphics._hulpbestanden()` naar de werkmap van
// de renderer kopieert.
import titel20Html from "../../../brands/sjablonen/titel20.html?raw";
import titel20Js from "../../../brands/sjablonen/titel20.js?url";
import "../../../brands/sjablonen/titel20.css";
import "../../../brands/fonts/titelfonts.css";

/** Het lijf van het sjabloon, zonder de scripts: die laden we zelf, in de
 *  volgorde die het sjabloon verwacht (eerst de variabelen, dan titel20.js). */
const LIJF = titel20Html
  .replace(/[\s\S]*<body[^>]*>/i, "")
  .replace(/<\/body>[\s\S]*/i, "")
  .replace(/<script[\s\S]*?<\/script>/gi, "");

/** Zoveel seconden vóór zijn tijd wordt een titel al opgebouwd. Het meten van
 *  de tekstmaat wacht op `document.fonts`, en dat kost een paar frames. */
const VOORUIT = 0.6;

type Props = {
  project: string;
  /** Verandert zodra de montage een andere titelstand heeft — bijvoorbeeld na
   *  opnieuw regisseren. Zonder dit bleef de oude titel boven de nieuwe
   *  beelden staan: `Bijwerken` vervangt de montagestand maar houdt hetzelfde
   *  project en dezelfde speler gemonteerd, en `project.titels` werd alleen
   *  bij een projectwissel opnieuw gevraagd. */
  revisie?: string;
  /** De tijdlijnklok van de speler. Een ref en geen prop: anders zou elke
   *  tekenslag een React-render kosten. */
  tijd: React.RefObject<number>;
  /** Het canvas waar de laag overheen ligt. De titels moeten op het *beeld*
   *  staan, niet op het canvas-element: dat is vaak breder dan het beeld, en
   *  `object-fit: contain` zet er zwarte randen omheen. */
  beeld: React.RefObject<HTMLCanvasElement | null>;
};

declare global {
  interface Window {
    __hyperframes?: { getVariables: () => Record<string, unknown> };
    __timelines?: Record<string, gsap.core.Timeline | undefined>;
  }
}

export default function Titels({ project, revisie, tijd, beeld }: Props) {
  const vak = useRef<HTMLDivElement | null>(null);
  const doek = useRef<HTMLDivElement | null>(null);
  const [web, setWeb] = useState<Titelweb | null>(null);

  useEffect(() => {
    let geldig = true;
    projectTitels(project)
      .then((t) => geldig && setWeb(t))
      .catch(() => geldig && setWeb(null));
    return () => {
      geldig = false;
    };
  }, [project, revisie]);

  // -- de laag over het beeld leggen ---------------------------------------
  // Hetzelfde rekensommetje als `object-fit: contain`: het grootste kader met
  // de verhouding van het canvas dat in het element past, gecentreerd. Staat de
  // titel daarnaast, dan staat hij in de export ergens anders dan hier.
  useEffect(() => {
    const d = doek.current;
    const c = beeld.current;
    if (!d || !c || !web || web.breedte === 0) return;
    const meet = () => {
      const schaal = Math.min(c.clientWidth / web.breedte, c.clientHeight / web.hoogte);
      const x = (c.clientWidth - web.breedte * schaal) / 2;
      const y = (c.clientHeight - web.hoogte * schaal) / 2;
      d.style.transform = `translate(${x}px, ${y}px) scale(${schaal})`;
    };
    meet();
    const kijker = new ResizeObserver(meet);
    kijker.observe(c);
    return () => kijker.disconnect();
  }, [web, beeld]);

  // -- de composities opbouwen en op de klok zetten ------------------------
  useEffect(() => {
    const d = doek.current;
    if (!d || !web || web.titels.length === 0) return;
    // `titel20.js` praat met de globale `gsap`; die komt uit de app-bundel,
    // zodat de voorvertoning ook zonder internet werkt.
    (window as unknown as { gsap: typeof gsap }).gsap = gsap;

    let draait = true;
    let handvat = 0;
    /** Welke titels nú in beeld horen. De bouwlus leest dit terug: tussen
     *  "begin te bouwen" en "klaar" kan de gebruiker verder gescrubd zijn. */
    const gewenst = new Set<string>();
    /** Wat er staat: per titel het vak in de DOM en zijn tijdlijn. */
    const open = new Map<string, { vak: HTMLDivElement; tl: gsap.core.Timeline | null }>();
    const bezig = new Set<string>();
    /** Eén voor één bouwen — zie punt 4 bovenaan dit bestand. */
    let wachtrij: Promise<void> = Promise.resolve();

    const sluit = (id: string) => {
      const o = open.get(id);
      if (!o) return;
      open.delete(id);
      o.tl?.kill();
      o.vak.remove();
    };

    /** De globale namen teruggeven aan het volgende vak. De opmaak hangt aan
     *  de classes, dus het vak blijft eruitzien zoals het eruitzag. */
    const geefIdsVrij = (vak: HTMLElement) => {
      for (const el of vak.querySelectorAll<HTMLElement>("[id]")) {
        el.setAttribute("data-id", el.id);
        el.removeAttribute("id");
      }
    };

    /** De tijdlijn komt pas als `document.fonts` klaar is; tot die tijd staat
     *  er niets in beeld, en dat is beter dan tekst in het verkeerde font.
     *  Komt hij helemaal niet, dan blijft het vak staan zonder te bewegen —
     *  wachten tot in het oneindige zou de volgende titel blokkeren.
     *
     *  Het antwoord zit in een doosje omdat een GSAP-tijdlijn zelf een `then`
     *  heeft: een promise die er rechtstreeks op uitkomt, wacht niet op de
     *  tijdlijn maar op het *afspelen* ervan. */
    const wachtOpTijdlijn = () =>
      new Promise<{ tl: gsap.core.Timeline | null }>((klaar) => {
        const begin = performance.now();
        const kijk = () => {
          const tl = window.__timelines?.titel20 ?? null;
          if (tl || !draait || performance.now() - begin > 5000) klaar({ tl });
          else requestAnimationFrame(kijk);
        };
        kijk();
      });

    const bouw = async (titel: Titelweb["titels"][number], nr: number) => {
      if (!draait || !gewenst.has(titel.id)) return;
      const vak = document.createElement("div");
      vak.className = "titel20-vak";
      vak.dataset.nr = String(nr);
      vak.innerHTML = LIJF;
      const wortel = vak.querySelector("#root") as HTMLElement | null;
      if (wortel) {
        wortel.setAttribute("data-width", String(web.breedte));
        wortel.setAttribute("data-height", String(web.hoogte));
      }
      // Dezelfde stapelvolgorde als de export: die legt de overlays in de
      // volgorde van `edl.json` over elkaar, dus de laatste ligt bovenop.
      const na =
        Array.from(d.children).find((k) => Number((k as HTMLElement).dataset.nr) > nr) ?? null;
      d.insertBefore(vak, na);
      window.__hyperframes = { getVariables: () => titel.variabelen };
      if (window.__timelines) delete window.__timelines.titel20;
      const script = document.createElement("script");
      script.src = titel20Js;
      document.body.appendChild(script);
      const { tl } = await wachtOpTijdlijn();
      script.remove();
      if (window.__timelines) delete window.__timelines.titel20;
      geefIdsVrij(vak);
      if (!draait || !gewenst.has(titel.id)) {
        tl?.kill();
        vak.remove();
        return;
      }
      open.set(titel.id, { vak, tl });
    };

    const lus = () => {
      if (!draait) return;
      handvat = requestAnimationFrame(lus);
      const t = tijd.current ?? 0;

      gewenst.clear();
      for (const x of web.titels) {
        if (t >= x.start - VOORUIT && t < x.start + x.duur) gewenst.add(x.id);
      }
      for (const id of [...open.keys()]) {
        if (!gewenst.has(id)) sluit(id);
      }
      web.titels.forEach((titel, nr) => {
        if (!gewenst.has(titel.id) || open.has(titel.id) || bezig.has(titel.id)) return;
        bezig.add(titel.id);
        wachtrij = wachtrij.then(() => bouw(titel, nr)).finally(() => bezig.delete(titel.id));
      });
      for (const titel of web.titels) {
        const tl = open.get(titel.id)?.tl;
        if (!tl) continue;
        tl.time(Math.max(0, Math.min(tl.duration(), t - titel.start)));
      }
    };
    handvat = requestAnimationFrame(lus);
    return () => {
      draait = false;
      cancelAnimationFrame(handvat);
      gewenst.clear();
      for (const id of [...open.keys()]) sluit(id);
      if (window.__timelines) delete window.__timelines.titel20;
      d.innerHTML = "";
    };
  }, [web, tijd]);

  if (!web || web.titels.length === 0) return null;
  return (
    <div className="titel20-laag" ref={vak} aria-hidden="true">
      <div
        className="titel20-doek"
        ref={doek}
        style={{ width: `${web.breedte}px`, height: `${web.hoogte}px` }}
      />
    </div>
  );
}
