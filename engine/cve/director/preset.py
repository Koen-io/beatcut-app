"""De preset-regisseur: montage zonder AI.

Werkt in vier stappen:

  1. Bouw het snijraster uit de muziek: tellen volgens het patroon van de
     montagestijl, gebogen door het energieniveau van de sectie
  2. Kies per snijmoment het beste nog vrije segment
  3. Bewaak variatie: niet twee keer dezelfde clip achter elkaar, geen twee
     visueel bijna identieke shots naast elkaar
  4. Schrijf de EDL, met per blok de reden erbij

Deze regisseur haalt geen 100 % van wat een mens zou doen, maar wel het
overgrote deel - en hij kost niets en draait offline.
"""

from __future__ import annotations

from .. import montagestijl as montage_mod, paths, stijl as stijl_mod
from ..analyze import beeld as beeld_mod
from ..edl import EDL, AudioSpoor, Canvas, Grade, Overgang, VideoBlok, gemiddelde_snelheid
from .basis import Brief, Regisseur, Voorstel

# Onder deze visuele gelijkenis mogen twee shots naast elkaar staan.
MAX_GELIJKENIS_NAAST = 0.82

# Een scene mag pas na dit aantal shots terugkomen. Zonder deze regel kwam
# hetzelfde tafereel drie keer voorbij in de eerste twaalf shots: ontdubbelen
# binnen een clip is niet genoeg als twee clips hetzelfde laten zien.
GEHEUGEN_SHOTS = 8
MAX_GELIJKENIS_GEHEUGEN = 0.74

# Dezelfde scene (zelfde plek, zelfde moment van de dag) mag niet vaker dan
# dit aantal shots achter elkaar terugkomen. Scenes komen uit de opnametijd
# van de camera - dat weet beter dan de pixels of je nog op dezelfde plek stond.
SCENE_GEHEUGEN = 4

# Dezelfde bronclip mag pas na dit aantal shots terugkomen. Met alleen "niet
# twee keer achter elkaar" kwam dezelfde clip vier keer binnen vier shots
# terug: tachtig shots uit 43 segmenten betekent dat elk segment ongeveer twee keer
# aan bod komt, en dan is de vorige-clip-regel te kort van geheugen.
CLIP_GEHEUGEN = 4

# Hoeveel een clip van "moet erin" (stap 4) erbij krijgt bij de keuze. Ruim
# boven het verschil tussen de beste en de slechtste kandidaat, zodat zo'n
# clip het eerste vak pakt waar hij in past, maar niet buiten de regels om:
# de variatiegrenzen gelden onverkort.
VOORKEUR_BONUS = 2.0

VORMEN = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


# Kortste shot waarin een speed-ramp nog als beweging leest (seconden).
RAMP_MIN_DUUR = 0.9

class PresetRegisseur(Regisseur):
    naam = "preset"
    heeft_model = False

    def stel_voor(self, analyse: dict, brief: Brief) -> Voorstel:
        waarschuwingen: list[str] = []
        muziek = analyse.get("muziek")
        segmenten = list(analyse.get("segmenten") or [])
        if not segmenten:
            raise RuntimeError("analysis.json bevat geen segmenten. Draai eerst `cve analyse`.")

        clip_op_id = {c["id"]: c for c in analyse["clips"]}
        segmenten = [s for s in segmenten if s["clip"] not in brief.uitgesloten]

        breedte, hoogte = VORMEN.get(brief.vorm, VORMEN["16:9"])
        canvas = Canvas(breedte=breedte, hoogte=hoogte, fps=30)

        st = stijl_mod.laad(brief.stijl, paths.STYLES)
        # Montagestijl: leeg betekent "wat bij dit soort beelden past".
        mst = montage_mod.laad(
            brief.montage or montage_mod.standaard_bij(brief.stijl), paths.STYLES
        )
        waarschuwingen.extend(mst.waarschuwingen)
        segmenten = self._herscoor(segmenten, analyse.get("gewichten") or {}, st)
        # Het langste bruikbare stuk beeld begrenst het snijpatroon: een shot
        # van vier maten kan niet uit een segment van twee seconden komen.
        langste = max((float(s["duur"]) for s in segmenten), default=0.0)
        raster, raster_offset = self._raster(
            muziek, brief, st, mst, langste, waarschuwingen
        )
        if not raster:
            raise RuntimeError("Kon geen snijraster maken. Is er een muziektrack?")

        edl = EDL(
            project=analyse["project"],
            stijl=brief.stijl,
            merk=brief.merk,
            canvas=canvas,
            grade=Grade(
                contrast=st.grade.get("contrast", 1.08),
                verzadiging=st.grade.get("verzadiging", 1.12),
                warmte=st.grade.get("warmte", 0.10),
            ),
        )

        # Blokken die de gebruiker heeft vastgezet gaan er sowieso in.
        for i, vast in enumerate(brief.vastgezet):
            clip = clip_op_id.get(vast["clip"])
            if not clip:
                waarschuwingen.append(f"Vastgezette clip {vast['clip']} bestaat niet.")
                continue
            edl.video.append(
                VideoBlok(
                    id=f"vast{i + 1}",
                    clip=clip["id"],
                    bestand=clip["bestand"],
                    bron_start=float(vast["bron_start"]),
                    duur=float(vast["duur"]),
                    tijdlijn_start=0.0,
                    vulmodus=self._vulmodus(clip, canvas),
                    reden="door jou vastgezet",
                    vast=True,
                )
            )

        gebruikt: set[tuple[str, float]] = set()
        recente_clips: list[str] = []
        recente_hashes: list[int] = []
        recente_scenes: list[int] = []
        teller = 0
        # Telt alleen de shots die daadwerkelijk een beweging kregen, zodat de
        # richting per keer verspringt en niet per shot.
        bewegingen = 0

        for tijd, lengte, niveau in raster:
            if brief.doelduur and tijd >= brief.doelduur:
                break

            # Snelheid en bevriezen komen uit de montagestijl en gelden alleen
            # op het energieniveau dat die stijl noemt. Beide raken de
            # tijdlijn niet: `snelheid` verandert hoeveel bron er opgaat,
            # `bevriezen` verdeelt de frames binnen hetzelfde blok.
            snelheid = mst.snelheid if mst.geldt("snelheid_bij", niveau) else 1.0
            bevriezen = mst.bevriezen if mst.geldt("bevriezen_bij", niveau) else 0.0
            bevriezen = min(bevriezen, max(0.0, lengte - 1.0 / canvas.fps))
            # Een ramp wil ruimte: onder RAMP_MIN_DUUR zie je hem niet, alleen
            # een hapering. Met een bevroren staart erbij ook niet.
            verloop = (
                mst.verloop()
                if mst.geldt("ramp_bij", niveau) and lengte >= RAMP_MIN_DUUR and bevriezen == 0
                else []
            )
            bron_nodig = lengte * (gemiddelde_snelheid(verloop) if verloop else snelheid)

            # Regels stap voor stap loslaten. Bij een handvol clips zijn er te
            # weinig kandidaten om aan alles te voldoen; dan is een herhaling
            # beter dan een montage die halverwege ophoudt.
            # De clip-afstand gaat als laatste los. Op de 21 testclips liepen
            # acht van de tachtig shots via een soepeler niveau, en juist daar
            # kwam dezelfde clip binnen vier shots terug.
            niveaus_van_soepelheid = (
                dict(gebruikt=gebruikt, clips=recente_clips, hashes=recente_hashes, scenes=recente_scenes),
                dict(gebruikt=gebruikt, clips=recente_clips, hashes=[], scenes=[]),
                dict(gebruikt=set(), clips=recente_clips, hashes=[], scenes=[]),
                dict(gebruikt=set(), clips=[], hashes=[], scenes=[]),
            )
            keuze = None
            for i, soepel in enumerate(niveaus_van_soepelheid):
                keuze = self._kies(
                    segmenten,
                    bron_nodig=bron_nodig,
                    niveau=niveau,
                    gebruikt=soepel["gebruikt"],
                    recente_clips=soepel["clips"],
                    recente_hashes=soepel["hashes"],
                    recente_scenes=soepel["scenes"],
                    clip_op_id=clip_op_id,
                    eerste=teller == 0 and i == 0,
                    st=st,
                    voorkeur=set(brief.voorkeur),
                )
                if keuze is not None:
                    if i >= 2:
                        gebruikt.clear()
                    break
            if keuze is None:
                waarschuwingen.append(
                    f"Te weinig bruikbaar materiaal voor shots van {lengte:.1f}s. "
                    f"Voeg clips toe of kies een montagestijl met kortere shots."
                )
                break

            seg, hash_waarde = keuze
            clip = clip_op_id[seg["clip"]]
            teller += 1

            # Snijd het segment op de rasterlengte, gecentreerd op zijn beste stuk.
            bron_start = seg["start"]
            if seg["duur"] > bron_nodig:
                bron_start = seg["start"] + (seg["duur"] - bron_nodig) / 2.0

            overgang = self._overgang(mst, teller)
            vulmodus = self._vulmodus(clip, canvas)
            zoom, zoom_kracht = self._ken_burns(
                seg, lengte, vulmodus, st, mst, bewegingen
            )
            if zoom != "geen":
                bewegingen += 1
            edl.video.append(
                VideoBlok(
                    id=f"v{teller:03d}",
                    clip=clip["id"],
                    bestand=clip["bestand"],
                    bron_start=round(bron_start, 3),
                    duur=round(lengte, 3),
                    tijdlijn_start=round(tijd, 3),
                    snelheid=snelheid,
                    snelheid_verloop=verloop,
                    bevriezen=round(bevriezen, 3),
                    vulmodus=vulmodus,
                    zoom=zoom,
                    zoom_kracht=zoom_kracht,
                    overgang_in=overgang,
                    reden=self._reden(seg, niveau, analyse.get("gewichten", {})),
                )
            )
            gebruikt.add((seg["clip"], seg["start"]))
            recente_clips.append(seg["clip"])
            recente_hashes.append(hash_waarde)
            recente_scenes.append(int(seg.get("scene", -1)))
            del recente_clips[:-GEHEUGEN_SHOTS]
            del recente_hashes[:-GEHEUGEN_SHOTS]
            del recente_scenes[:-GEHEUGEN_SHOTS]

        # Framevast maken vóór het audiospoor: de duur van de montage moet
        # kloppen met wat de renderer straks daadwerkelijk oplevert.
        edl.op_framerooster()

        if muziek:
            edl.audio.append(
                AudioSpoor(
                    bestand=muziek["bestand"],
                    # De montage begint op het eerste snijpunt in de muziek.
                    # Door de track daar te laten beginnen valt snede 1 exact
                    # op die tel, en alle volgende ook.
                    bron_start=round(raster_offset, 3),
                    duur=edl.duur,
                    volume=1.0,
                    fade_in=0.3,
                    fade_out=min(2.5, edl.duur / 4),
                )
            )

        # Standaard-overlays: een openingstitel en een eindkaart. Alleen als de
        # brief er iets voor aanlevert - een lege titel levert geen kaart op.
        if brief.titel or brief.slottekst:
            from ..graphics import standaard_overlays

            edl.overlay.extend(
                standaard_overlays(
                    edl,
                    titel=brief.titel,
                    eyebrow=brief.eyebrow,
                    onder=brief.ondertitel,
                    slot=brief.slottekst,
                )
            )

        uitleg = self._uitleg(edl, muziek, brief, st, mst)
        return Voorstel(edl=edl, uitleg=uitleg, waarschuwingen=waarschuwingen)

    # -- hulpstukken --------------------------------------------------------

    def _raster(
        self,
        muziek: dict | None,
        brief: Brief,
        st: stijl_mod.Stijl,
        mst: montage_mod.Montagestijl,
        langste_segment: float,
        waarschuwingen: list[str],
    ) -> tuple[list[tuple[float, float, str]], float]:
        """Snijmomenten met shotlengte en energieniveau.

        Loopt over het **tel**-raster uit `analysis.json` en stapt daar per
        shot zoveel tellen op als het patroon van de montagestijl zegt. Daarmee
        is "snedes liggen op de tel" geen nabewerking maar een eigenschap van de
        constructie: elk snijpunt *is* een gedetecteerde tel.

        Het energieniveau van de sectie buigt binnen het patroon: in een drop
        het kortste getal eruit, in een rustige passage het langste. Dus geen
        factor die van buiten komt - alleen de getallen die de stijl zelf noemt.

        Geeft ook terug op welke seconde in de muziek de montage begint. Die
        offset gaat naar het audiospoor, zodat snede 1 exact op een tel valt.
        """
        if not muziek:
            # Zonder muziek is er geen tel. Dan houden we het patroon aan op
            # 120 BPM (een halve seconde per tel) en zeggen we dat erbij.
            lengte = max(st.ritme.min_shot, mst.gemiddeld * 0.5)
            waarschuwingen.append(f"Geen muziek; vaste shotlengte van {lengte:.1f}s gebruikt.")
            duur = brief.doelduur or 60.0
            n = int(duur // lengte)
            return [(i * lengte, lengte, "opbouw") for i in range(n)], 0.0

        secties = muziek["secties"]
        beats = [b for b in muziek["beats"] if b >= brief.muziek_start]
        if len(beats) < 2:
            waarschuwingen.append("Geen tellen gevonden in de muziek.")
            return [], 0.0

        def niveau_op(t: float) -> str:
            for s in secties:
                if s["start"] <= t < s["eind"]:
                    return s["niveau"]
            return "opbouw"

        tel_duur = 60.0 / muziek["bpm"] if muziek.get("bpm") else beats[1] - beats[0]
        offset = beats[0]

        # Hoeveel tellen een shot hoogstens kan duren met dít materiaal. De
        # 0,95 is marge: tussen twee gedetecteerde tellen zit niet exact
        # `tel_duur`, en een shot dat een fractie langer uitvalt dan het
        # langste segment levert geen enkele kandidaat op.
        plafond = max(1, int(langste_segment * 0.95 / tel_duur)) if tel_duur > 0 else 1
        if plafond < max(mst.patroon):
            waarschuwingen.append(
                f"Het langste bruikbare stuk beeld is {langste_segment:.1f}s; shots van "
                f"{max(mst.patroon):.0f} tellen passen daar niet in en zijn ingekort."
            )

        raster: list[tuple[float, float, str]] = []
        i = 0
        shot = 0
        laatste = len(beats) - 1
        while i < laatste:
            t = beats[i]
            niveau = niveau_op(t)
            tellen = mst.tellen(shot)
            if niveau == "hoog":
                tellen = min(mst.patroon)
            elif niveau == "rustig":
                tellen = max(mst.patroon)
            stap = max(1, min(int(round(tellen)), plafond))

            j = min(i + stap, laatste)
            lengte = beats[j] - t
            if lengte <= 0.05:
                i += 1
                continue
            raster.append((round(t - offset, 3), round(lengte, 3), niveau))
            shot += 1
            i = j
            if brief.doelduur and t - offset + lengte >= brief.doelduur:
                break

        return raster, offset

    def _kies(
        self,
        segmenten: list[dict],
        *,
        bron_nodig: float,
        niveau: str,
        gebruikt: set,
        recente_clips: list[str],
        recente_hashes: list[int],
        recente_scenes: list[int],
        clip_op_id: dict,
        eerste: bool,
        st: stijl_mod.Stijl,
        voorkeur: set[str] | None = None,
    ) -> tuple[dict, int] | None:
        """Beste segment dat aan alle regels voldoet."""
        beste = None
        beste_waarde = -1e9
        verboden_clips = set(recente_clips[-CLIP_GEHEUGEN:])
        vorige_hash = recente_hashes[-1] if recente_hashes else 0
        verboden_scenes = set(recente_scenes[-SCENE_GEHEUGEN:])

        al_gebruikt = {c for c, _ in gebruikt}
        for seg in segmenten:
            sleutel = (seg["clip"], seg["start"])
            if sleutel in gebruikt:
                continue
            if seg["duur"] < bron_nodig - 0.01:
                # "Moet erin" weegt zwaarder dan "mooiste stuk": is geen enkel
                # bruikbaar stuk lang genoeg, neem dan het venster rond dit
                # stuk, zolang de clip zelf lang genoeg is.
                seg = self._verbreed(seg, bron_nodig, clip_op_id) if (
                    voorkeur and seg["clip"] in voorkeur and seg["clip"] not in al_gebruikt
                ) else None
                if seg is None:
                    continue
            if seg["clip"] in verboden_clips:
                continue
            if seg.get("scene") in verboden_scenes:
                continue

            hash_waarde = self._hash_van(seg, clip_op_id)
            if hash_waarde:
                if vorige_hash and beeld_mod.gelijkenis(hash_waarde, vorige_hash) > MAX_GELIJKENIS_NAAST:
                    continue
                # Kijk verder terug: hetzelfde tafereel mag niet binnen een
                # paar shots terugkomen, ook niet uit een andere clip.
                if any(
                    h and beeld_mod.gelijkenis(hash_waarde, h) > MAX_GELIJKENIS_GEHEUGEN
                    for h in recente_hashes[:-1]
                ):
                    continue

            waarde = seg["score"]
            ond = seg.get("onderdelen", {})
            if niveau == "hoog":
                if st.ritme.drops == "beeld":
                    # Het tempo blijft gelijk; de energie moet uit de beeldkeuze
                    # komen. Daarom hier een flinke bonus op de ruwe score, zodat
                    # de sterkste shots in de drop terechtkomen.
                    waarde += 0.45 * seg["score"] + 0.10 * ond.get("beweging", 0.0)
                else:
                    waarde += 0.15 * ond.get("beweging", 0.0)
            elif niveau == "rustig":
                waarde += 0.15 * ond.get("scherpte", 0.0) - 0.10 * ond.get("shake", 0.0)
            if voorkeur and seg["clip"] in voorkeur:
                # "Moet erin": voorrang bij elke keuze tot de clip aan bod is
                # geweest. `gebruikt` houdt hem daarna van het volgende vak af.
                waarde += VOORKEUR_BONUS
            if eerste:
                # De opening moet de sterkste hook zijn: scherp en met beweging.
                waarde += 0.20 * ond.get("beweging", 0.0) + 0.20 * ond.get("scherpte", 0.0)

            if waarde > beste_waarde:
                beste_waarde = waarde
                beste = (seg, hash_waarde)

        return beste

    @staticmethod
    def _verbreed(seg: dict, bron_nodig: float, clip_op_id: dict) -> dict | None:
        """Een te kort segment van een moet-clip, opgerekt binnen de clip."""
        clip = clip_op_id.get(seg["clip"]) or {}
        clipduur = float(clip.get("duur") or 0.0)
        if clipduur < bron_nodig:
            return None
        midden = (seg["start"] + seg["eind"]) / 2.0
        start = min(max(0.0, midden - bron_nodig / 2.0), clipduur - bron_nodig)
        breed = dict(seg)
        breed.update(start=round(start, 3), eind=round(start + bron_nodig, 3),
                     duur=bron_nodig, verbreed=True)
        # Net onder een echt passend stuk van dezelfde clip.
        breed["score"] = float(seg.get("score", 0.0)) - 0.05
        return breed

    @staticmethod
    def _hash_van(seg: dict, clip_op_id: dict) -> int:
        clip = clip_op_id.get(seg["clip"])
        if not clip:
            return 0
        reeks = clip.get("reeks", {})
        tijden = reeks.get("tijden") or []
        hashes = reeks.get("hashes") or []
        if not tijden or not hashes:
            return 0
        midden = (seg["start"] + seg["eind"]) / 2.0
        idx = min(range(len(tijden)), key=lambda i: abs(tijden[i] - midden))
        return int(hashes[idx]) if idx < len(hashes) else 0

    @staticmethod
    def _vulmodus(clip: dict, canvas: Canvas) -> str:
        """Verticale clip in een liggend canvas krijgt een wazige achtergrond."""
        clip_verticaal = clip.get("verticaal", False)
        canvas_verticaal = canvas.hoogte > canvas.breedte
        if clip_verticaal != canvas_verticaal:
            return "wazig"
        return "vul"

    @staticmethod
    def _herscoor(
        segmenten: list[dict], analyse_gewichten: dict, st: stijl_mod.Stijl
    ) -> list[dict]:
        """Geef elk segment een score volgens *deze* stijl.

        De score in `analysis.json` is berekend met de gewichten van de stijl
        die tijdens `cve analyse` gold. Dat betekende dat `cve regie --stijl X`
        alleen het ritme veranderde en niet de shotkeuze: de volgorde van
        kandidaten stond al vast. Precies daardoor had ook een geleerde
        bijstelling geen enkel effect.

        Herrekenen kan zonder de analyse over te doen, want de losse signalen
        staan per segment in `onderdelen`. We trekken de oude weging eraf en
        tellen de nieuwe erbij op:

            nieuw = opgeslagen − Σ w_analyse·o + Σ w_stijl·o

        Wat overblijft van de opgeslagen score is de vormbonus
        (`lengte_voorkeur` en `consistentie`) die in `segmenten.py` op het
        venster zelf slaat en niet uit `onderdelen` te herleiden is. Die laten
        we dus precies staan.
        """
        if not analyse_gewichten:
            return segmenten

        nieuw_g = st.gewichten.signalen()
        uit = []
        for s in segmenten:
            ond = s.get("onderdelen") or {}
            if not ond:
                uit.append(s)
                continue
            oud_deel = sum(float(analyse_gewichten.get(k, 0.0)) * v for k, v in ond.items())
            nieuw_deel = sum(float(nieuw_g.get(k, 0.0)) * v for k, v in ond.items())
            kopie = dict(s)
            kopie["score"] = round(float(s.get("score", 0.0)) - oud_deel + nieuw_deel, 4)
            uit.append(kopie)
        return uit

    # Vaste volgorde, zodat twee stilstaande shots achter elkaar niet dezelfde
    # kant op bewegen. Inzoomen is de rustigste en staat daarom vooraan.
    KEN_BURNS_CYCLUS = ("in", "rechts", "uit", "links", "in", "omlaag", "uit", "omhoog")

    @classmethod
    def _ken_burns(
        cls, seg: dict, lengte: float, vulmodus: str, st, mst, gezet: int
    ) -> tuple[str, float]:
        """Geef een stilstaand shot een trage beweging mee.

        Wat de review als "beeld staat stil zonder dat dat gevraagd is"
        aanmerkt, wordt hier bij de bron opgelost: de bewegingsscore staat al
        in de analyse, dus de regisseur kan het zien aankomen.

        Alleen bij `vul`. Een verticale clip op een liggend canvas staat in
        het midden met een wazige achtergrond eromheen; daar zou een zoom de
        randen van het beeld afsnijden en een pan de compositie uit het
        midden trekken.
        """
        bw = st.beweging
        if not mst.ken_burns:
            # De montagestijl snijdt te snel voor een trage beweging.
            return "geen", 0.12
        # Marge van 10 % op de ondergrens, net als bij `min_shot` in `_raster`.
        # Een halve maat is bij 123 BPM 1,95 s en `min_duur` van reis staat op
        # 2,0: zonder marge viel 49 van de 80 shots net buiten de boot en kreeg
        # 78 van de 80 geen beweging, terwijl de stijl `ken_burns: ja` zegt.
        if not bw.ken_burns or vulmodus != "vul" or lengte < bw.min_duur * 0.9:
            return "geen", 0.12

        # De montagestijl mag de drempel verhogen: bij shots van vier maten
        # valt ook een licht bewegend beeld stil, en dan is een trage duw juist
        # wat de stijl vraagt.
        drempel = mst.ken_burns_drempel or bw.drempel
        score = float((seg.get("onderdelen") or {}).get("beweging", 1.0))
        if score >= drempel:
            return "geen", 0.12

        # Hoe stiller het shot, hoe meer duw het kan hebben.
        aandeel = 1.0 - (score / drempel if drempel > 0 else 0.0)
        kracht = bw.kracht + (bw.kracht_max - bw.kracht) * max(0.0, min(1.0, aandeel))
        if mst.ken_burns_kracht > 0:
            # De montagestijl noemt een kracht; die gaat voor op die van het
            # soort beelden. Cinematisch reizen vraagt 4 %, Vlog 10 %.
            kracht = mst.ken_burns_kracht
        return cls.KEN_BURNS_CYCLUS[gezet % len(cls.KEN_BURNS_CYCLUS)], round(kracht, 3)

    @staticmethod
    def _overgang(mst: montage_mod.Montagestijl, index: int) -> Overgang:
        """De overgang vóór shot `index`, zoals de montagestijl hem voorschrijft.

        Alleen namen die `render.py` echt kan; `montagestijl.laad()` heeft de
        rest er al uitgehaald met een waarschuwing erbij. Het openingsshot komt
        altijd uit zwart op - dat is geen stijlkeuze maar het begin van een film.
        """
        if index == 1:
            return Overgang("dip_zwart", 0.4)
        soort, duur = mst.overgang_voor(index)
        return Overgang(soort, duur)

    @staticmethod
    def _reden(seg: dict, niveau: str, gewichten: dict) -> str:
        """Toon wat er werkelijk bijdroeg, niet wat toevallig hoog stond."""
        ond = seg.get("onderdelen", {})
        bijdrage = {k: gewichten.get(k, 0.0) * v for k, v in ond.items()}
        top = sorted(bijdrage.items(), key=lambda kv: -abs(kv[1]))[:2]
        kern = ", ".join(f"{k} {v:+.2f}" for k, v in top if abs(v) > 0.001)
        return f"{niveau}: {kern} (score {seg['score']:.2f})"

    @staticmethod
    def _uitleg(
        edl: EDL,
        muziek: dict | None,
        brief: Brief,
        st: stijl_mod.Stijl,
        mst: montage_mod.Montagestijl,
    ) -> str:
        clips = {b.clip for b in edl.video}
        lengtes = [b.duur for b in edl.video]
        # Nul shots kan: te weinig bruikbaar materiaal voor de shotlengte van
        # deze stijl. Dan staat de echte uitleg in de waarschuwingen, en mag
        # het gemiddelde geen ZeroDivisionError worden.
        gemiddeld = sum(lengtes) / len(lengtes) if lengtes else 0.0
        regels = [
            f"{mst.titel} op {st.titel.lower()}: {len(edl.video)} shots uit "
            f"{len(clips)} clips, samen {edl.duur:.1f}s "
            f"(gemiddeld {gemiddeld:.1f}s per shot)."
        ]
        if muziek:
            tel_duur = 60.0 / muziek["bpm"] if muziek.get("bpm") else 0.0
            in_tellen = gemiddeld / tel_duur if tel_duur > 0 else 0.0
            regels.append(
                f"Gesneden op het tel-raster van {muziek['bpm']:.0f} BPM: "
                f"{mst.snijritme} ({in_tellen:.1f} tellen gemeten)."
            )
        traag = sum(1 for b in edl.video if b.snelheid != 1.0)
        if traag:
            regels.append(f"{traag} shots staan op {mst.snelheid:g}x.")
        stil = sum(1 for b in edl.video if b.bevriezen > 0)
        if stil:
            regels.append(f"{stil} shots eindigen op een stilstaand beeld.")
        wazig = sum(1 for b in edl.video if b.vulmodus == "wazig")
        if wazig:
            regels.append(f"{wazig} staande shots kregen een wazige achtergrond.")
        return " ".join(regels)
