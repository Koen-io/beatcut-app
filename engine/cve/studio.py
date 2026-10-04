"""Studio - de lokale timeline-editor.

Een kleine HTTP-server die `studio/index.html` serveert plus de gegevens die
de interface nodig heeft. Bewust zonder framework en zonder buildstap: het
moet straks zonder node-toolchain in een Tauri-schil passen.

De server houdt geen staat bij. `edl.json` is de waarheid; de interface leest
en schrijft dat bestand via deze server.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import media, paths
from . import projecten as projecten_mod
from .edl import EDL

THUMB_BREEDTE = 160
THUMB_HOOGTE = 90
THUMBS_PER_CLIP = 24


# --------------------------------------------------------------------------
# Voorbereiding: miniaturen en golfvorm
# --------------------------------------------------------------------------


def maak_thumbnails(project: str, *, log=print) -> Path:
    """Een strook miniaturen per clip, zodat de timeline beeld kan tonen."""
    pdir = paths.project_dir(project)
    doelmap = pdir / "cache" / "thumbs"
    doelmap.mkdir(parents=True, exist_ok=True)

    ingest = json.loads((pdir / "ingest.json").read_text(encoding="utf-8"))
    gemaakt = 0
    for clip in ingest["clips"]:
        doel = doelmap / f"{clip['id']}.jpg"
        if doel.exists():
            continue
        proxy = pdir / "proxies" / clip["proxy"]
        if not proxy.exists():
            continue
        duur = max(0.1, clip["duur"])
        fps = THUMBS_PER_CLIP / duur
        subprocess.run(
            [
                str(paths.ffmpeg()),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(proxy),
                "-vf",
                # Vaste beeldverhouding per miniatuur: bijsnijden op het midden
                # in plaats van uitrekken. Zonder dit worden staande clips
                # platgedrukt, want dan is elke strook een andere hoogte.
                f"fps={fps:.6f},"
                f"scale={THUMB_BREEDTE}:{THUMB_HOOGTE}:force_original_aspect_ratio=increase,"
                f"crop={THUMB_BREEDTE}:{THUMB_HOOGTE},"
                f"tile={THUMBS_PER_CLIP}x1",
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(doel),
            ],
            check=False,
            capture_output=True,
            timeout=600,
        )
        gemaakt += 1
    if gemaakt:
        log(f"{gemaakt} miniatuurstroken gemaakt")
    return doelmap


def maak_golfvorm(project: str, *, punten: int = 1800, log=print) -> Path | None:
    """Amplitude van de muziek als lijst getallen, voor de audiotrack."""
    pdir = paths.project_dir(project)
    doel = pdir / "cache" / "golfvorm.json"
    if doel.exists():
        return doel

    muziek = media.vind_muziek(pdir / "muziek")
    if not muziek:
        return None

    import numpy as np

    wav = media.haal_audio(muziek[0], pdir / "cache" / "muziek.wav", sr=8000)
    if wav is None:
        return None

    import wave

    with wave.open(str(wav), "rb") as w:
        ruw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)

    if ruw.size == 0:
        return None
    blok = max(1, len(ruw) // punten)
    bruikbaar = ruw[: blok * (len(ruw) // blok)].reshape(-1, blok)
    amp = np.abs(bruikbaar).max(axis=1)
    amp = amp / max(1.0, amp.max())
    doel.write_text(
        json.dumps({"punten": [round(float(v), 3) for v in amp]}), encoding="utf-8"
    )
    log(f"Golfvorm: {len(amp)} punten")
    return doel


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------


class StudioServer(ThreadingHTTPServer):
    """Server die tegen een browser kan.

    De standaardwaarden van `ThreadingHTTPServer` zijn hier te krap:

    - `request_queue_size` is standaard 5. Chrome opent zes gelijktijdige
      verbindingen per host, dus de zesde belandt in een wachtrij die vol is.
      Meestal is dat net het videoverzoek en dan blijft het beeld zwart.
    - Zonder timeout houdt elke inactieve keep-alive-verbinding een thread
      bezet. Na een paar herladingen zit alles vast.
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class StudioHandler(BaseHTTPRequestHandler):
    # Het project waarmee de server gestart is. Elk verzoek mag er met
    # `?project=` van afwijken, zodat het startscherm tussen projecten kan
    # wisselen zonder de server te herstarten.
    start_project: str = ""

    @property
    def project(self) -> str:
        q = parse_qs(urlparse(self.path).query)
        naam = (q.get("project") or [None])[0]
        if naam:
            veilig = projecten_mod.veilige_naam(naam)
            if (paths.PROJECTEN / veilig).exists():
                return veilig
        return self.start_project

    @property
    def pdir(self) -> Path:
        return paths.project_dir(self.project) if self.project else paths.PROJECTEN

    # Geen `timeout` op de handler: die geldt voor élke socketoperatie,
    # dus ook voor het wegschrijven van een video. Threads komen vrij zodra
    # de browser de verbinding sluit, en `request_queue_size` hierboven zorgt
    # dat er genoeg ruimte is om ze tot die tijd open te houden.

    # HTTP/1.1 met keep-alive is niet optioneel: Chrome's mediastack haalt een
    # video op in tientallen kleine Range-verzoeken en blijft op HTTP/1.0
    # eindeloos in networkState LOADING hangen. Dat kostte hier een debugronde.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        # Standaard stil. Zet CVE_STUDIO_DEBUG=1 om elk verzoek te zien - dat is
        # de enige manier om te zien of de browser wel bij ons aanklopt.
        if os.environ.get("CVE_STUDIO_DEBUG"):
            bereik = self.headers.get("Range", "-")
            print(f"  {self.command} {self.path}  Range={bereik}  -> {fmt % args}", flush=True)

    # -- hulpjes --------------------------------------------------------

    def _stuur(self, code: int, inhoud: bytes, mime: str, *, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(inhoud)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(inhoud)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    def _json(self, data, code: int = 200) -> None:
        self._stuur(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    # Grootste stuk dat we in een keer terugsturen bij een open Range-verzoek
    # (`bytes=0-`). Chrome vraagt zo het hele bestand op, laat het meestal na
    # een paar honderd kB vallen en verbreekt de verbinding. Als de server dan
    # nog 7 MB staat te schrijven, klapt de thread eruit en blijft de video op
    # `stalled` hangen. Kleine happen sturen lost dat op.
    MAX_BROK = 4 << 20

    def _bestand(self, pad: Path) -> None:
        """Serveer een bestand met Range-ondersteuning.

        Belangrijk: ook het verzoek *zonder* Range-header wordt in blokken
        gestreamd. Chrome vraagt een video eerst gewoon op zonder Range en
        verbreekt de verbinding zodra hij genoeg heeft. Wie dan nog megabytes
        in een keer staat weg te schrijven, krijgt een BrokenPipeError, de
        thread valt om en de video laadt nooit. Dat kostte hier drie
        debugrondes.
        """
        if not pad.exists() or not pad.is_file():
            self._json({"fout": f"niet gevonden: {pad.name}"}, 404)
            return

        mime = mimetypes.guess_type(pad.name)[0] or "application/octet-stream"
        grootte = pad.stat().st_size
        bereik = self.headers.get("Range")

        if bereik:
            m = re.match(r"bytes=(\d*)-(\d*)", bereik)
            start = int(m.group(1)) if m and m.group(1) else 0
            if m and m.group(2):
                eind = min(int(m.group(2)), grootte - 1)
            else:
                eind = min(start + self.MAX_BROK - 1, grootte - 1)
            start = max(0, min(start, grootte - 1))
            lengte = max(0, eind - start + 1)

            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{eind}/{grootte}")
        else:
            start, lengte = 0, grootte
            self.send_response(200)

        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(lengte))
        self.end_headers()

        self._stroom(pad, start, lengte)

    def _stroom(self, pad: Path, start: int, lengte: int) -> None:
        """Schrijf een stuk bestand weg in happen van 64 kB.

        Vangt de verbindingsfouten op die ontstaan als de browser vroegtijdig
        afhaakt - dat is normaal gedrag, geen fout.
        """
        geschreven = 0
        try:
            with pad.open("rb") as f:
                f.seek(start)
                over = lengte
                while over > 0:
                    blok = f.read(min(65536, over))
                    if not blok:
                        break
                    self.wfile.write(blok)
                    geschreven += len(blok)
                    over -= len(blok)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            self.close_connection = True
        if os.environ.get("CVE_STUDIO_DEBUG"):
            print(f"      {pad.name}: {geschreven}/{lengte} bytes geschreven", flush=True)

    # -- routes ---------------------------------------------------------

    def do_HEAD(self) -> None:  # noqa: N802
        """Chrome doet een HEAD voor het video's ophaalt. Zonder dit: 501."""
        pad = unquote(urlparse(self.path).path)
        doel = self._pad_naar_bestand(pad)
        if doel is None or not doel.exists():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(doel.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(doel.stat().st_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def _pad_naar_bestand(self, pad: str) -> Path | None:
        if pad in ("/", "/start", "/start.html"):
            return paths.ROOT / "studio" / "start.html"
        if pad in ("/studio", "/index.html", "/studio.html"):
            return paths.ROOT / "studio" / "index.html"
        if pad in ("/wizard", "/wizard.html"):
            return paths.ROOT / "studio" / "wizard.html"
        if pad in ("/ui.css", "/ui.js"):
            # Huisstijl van de interface: tokens, glas en de themaschakelaar.
            # Eén bestand voor alle drie de pagina's.
            return paths.ROOT / "studio" / Path(pad).name
        if pad == "/titelstijlen.css":
            # Dezelfde stijldefinitie die de sjablonen gebruiken. Zo kunnen
            # voorvertoning en render niet uit elkaar lopen.
            return paths.BRANDS / "sjablonen" / "titelstijlen.css"
        if pad.startswith("/media/proxy/"):
            return self.pdir / "proxies" / Path(pad).name
        if pad.startswith("/media/thumb/"):
            doel = self.pdir / "cache" / "thumbs" / Path(pad).name
            if not doel.exists() and (self.pdir / "ingest.json").exists():
                # Miniaturen worden pas gemaakt wanneer ze voor het eerst
                # gevraagd worden. Anders zou het openen van een ander project
                # een herstart van de server vragen.
                maak_thumbnails(self.project, log=lambda *_: None)
            return doel
        if pad.startswith("/media/muziek/"):
            return self.pdir / "muziek" / Path(pad).name
        if pad.startswith("/media/render/"):
            return self.pdir / "renders" / Path(pad).name
        return None

    def do_GET(self) -> None:  # noqa: N802
        pad = unquote(urlparse(self.path).path)

        if pad == "/api/projecten":
            self._json(
                {
                    "projecten": [projecten_mod.naar_dict(s) for s in projecten_mod.alle()],
                    "huidig": self.start_project,
                }
            )
            return

        if pad == "/api/status":
            if not self.project:
                self._json({"fout": "geen project"}, 404)
                return
            self._json(projecten_mod.naar_dict(projecten_mod.status(self.project)))
            return

        if pad == "/api/bronnen":
            self._bronnen()
            return

        if pad == "/api/stijlvoorstel":
            from . import stijlkeuze

            analyse_pad = self.pdir / "analysis.json"
            if not analyse_pad.exists():
                self._json({"fout": "nog niet geanalyseerd"}, 404)
                return
            v = stijlkeuze.kies(json.loads(analyse_pad.read_text(encoding="utf-8")))
            self._json(
                {
                    "stijl": v.stijl,
                    "zekerheid": v.zekerheid,
                    "zin": v.zin(),
                    "gemeten": v.gemeten,
                    "volgorde": v.volgorde,
                }
            )
            return

        if pad == "/api/titelvoorstel":
            # Welke titels de wizard zou plaatsen, vóórdat er iets gerenderd
            # wordt. Werkt op de montage als die er is, anders op de clips in
            # opnamevolgorde.
            from .titels import voorstel as _titelvoorstel

            q = parse_qs(urlparse(self.path).query)
            hoofdtitel = q.get("titel", [""])[0]
            online = q.get("online", ["0"])[0] == "1"
            ingest_pad = self.pdir / "ingest.json"
            edl_pad = self.pdir / "edl.json"
            if not ingest_pad.exists():
                self._json({"titels": []})
                return
            try:
                clips = {
                    c["id"]: c
                    for c in json.loads(ingest_pad.read_text(encoding="utf-8"))["clips"]
                }
                if edl_pad.exists():
                    blokken = json.loads(edl_pad.read_text(encoding="utf-8"))["video"]
                else:
                    # Nog geen montage: doe alsof elke clip achter elkaar staat.
                    blokken, t = [], 0.0
                    for c in clips.values():
                        blokken.append({"clip": c["id"], "tijdlijn_start": t,
                                        "duur": min(4.0, c.get("duur", 4.0))})
                        t += min(4.0, c.get("duur", 4.0))
                self._json({
                    "titels": _titelvoorstel(
                        blokken, clips, hoofdtitel=hoofdtitel, met_internet=online
                    )
                })
            except Exception as e:  # noqa: BLE001
                self._json({"titels": [], "fout": str(e)})
            return

        if pad == "/api/benodigdheden":
            from .benodigdheden import ontbreekt

            mist = ontbreekt()
            if paths.node_bin() is None:
                mist.append("node")
            if paths.hyperframes() is None:
                mist.append("hyperframes")
            self._json({"compleet": not mist, "ontbreekt": mist})
            return

        if pad == "/api/update":
            # In een aparte thread zou netter zijn, maar de controle valt na
            # één keer terug op een dagcache en heeft een korte timeout.
            from .update import kijk

            self._json(kijk().naar_dict())
            return

        if pad == "/api/voortgang":
            from . import voortgang as vg

            # `sleutel=__opstart__` volgt het eenmalige klaarzetten; zonder
            # sleutel de klus van het huidige project.
            sleutel = parse_qs(urlparse(self.path).query).get("sleutel", [""])[0]
            self._json(
                vg.stand(sleutel or self.project) or {"bezig": False, "fase": "niets"}
            )
            return

        if pad == "/api/project":
            self._project()
            return

        if pad == "/api/edl":
            edl_pad = self.pdir / "edl.json"
            if not edl_pad.exists():
                self._json({"fout": "geen edl.json"}, 404)
                return
            self._json(json.loads(edl_pad.read_text(encoding="utf-8")))
            return

        if pad == "/api/stijlen":
            from . import stijl as stijl_mod
            from .geheugen import laad_geleerd

            self._json(
                [
                    {
                        "naam": s.naam,
                        "titel": s.titel,
                        "omschrijving": s.omschrijving,
                        "min_shot": s.ritme.min_shot,
                        "max_shot": s.ritme.max_shot,
                        "drops": s.ritme.drops,
                        # Wat deze stijl uit eerdere keuzes heeft opgepikt.
                        # Zichtbaar maken is het halve werk: een systeem dat
                        # ongemerkt bijstelt voelt als willekeur.
                        "geleerd": {
                            "keuzes": laad_geleerd(s.naam).get("keuzes", 0),
                            "bijstelling": laad_geleerd(s.naam).get("bijstelling", {}),
                        },
                    }
                    for s in stijl_mod.alle(paths.STYLES)
                ]
            )
            return

        if pad == "/api/vergeet":
            from .geheugen import vergeet

            naam = parse_qs(urlparse(self.path).query).get("stijl", [""])[0]
            self._json({"ok": vergeet(naam)} if naam else {"fout": "geen stijl"})
            return

        doel = self._pad_naar_bestand(pad)
        if doel is not None:
            self._bestand(doel)
            return

        self._json({"fout": "onbekende route"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        pad = unquote(urlparse(self.path).path)
        lengte = int(self.headers.get("Content-Length", 0))

        # Uploads komen als rauwe bytes binnen, niet als JSON. Bewust geen
        # multipart: de browser stuurt een bestand tegelijk en de naam staat
        # in een eigen header. Scheelt een parser en werkt met grote bestanden.
        if pad == "/api/upload":
            self._upload(lengte)
            return

        lichaam = self.rfile.read(lengte) if lengte else b"{}"
        try:
            data = json.loads(lichaam)
        except json.JSONDecodeError:
            self._json({"fout": "ongeldige JSON"}, 400)
            return

        if pad == "/api/project/nieuw":
            naam = (data.get("naam") or "").strip()
            if not naam:
                self._json({"fout": "geef een naam op"}, 400)
                return
            self._json(projecten_mod.naar_dict(projecten_mod.maak(naam)))
            return

        if pad == "/api/project/verwijder":
            projecten_mod.verwijder(projecten_mod.veilige_naam(data.get("naam", "")))
            self._json({"ok": True})
            return

        if pad == "/api/verwerk":
            if not self.project:
                self._json({"fout": "geen project"}, 400)
                return
            projecten_mod.verwerk(
                self.project,
                stijl=data.get("stijl", "landschap"),
                opnieuw=bool(data.get("opnieuw")),
            )
            self._json({"ok": True})
            return

        if pad == "/api/openmap":
            if not self.project:
                self._json({"fout": "geen project"}, 400)
                return
            try:
                projecten_mod.open_map(self.project, data.get("map", "bronnen"))
            except Exception as e:  # noqa: BLE001
                self._json({"fout": str(e)}, 500)
                return
            self._json({"ok": True})
            return

        if pad == "/api/verwijder-clip":
            naam = Path(data.get("bestand", "")).name
            doel = self.pdir / ("muziek" if data.get("soort") == "muziek" else "bronnen") / naam
            if doel.exists():
                doel.unlink()
            self._json({"ok": True})
            return

        if pad == "/api/edl":
            try:
                edl = EDL.van_dict(data)
                edl.valideer()
                edl.schrijf(self.pdir / "edl.json")
            except Exception as e:  # noqa: BLE001
                self._json({"fout": str(e)}, 400)
                return
            self._json({"ok": True, "duur": edl.duur, "blokken": len(edl.video)})
            return

        if pad == "/api/regie":
            self._regie(data)
            return

        if pad == "/api/render":
            self._render(data)
            return

        if pad == "/api/review":
            self._review(data)
            return

        if pad == "/api/benodigdheden/haal":
            # Eenmalig klaarzetten bij de eerste start. Draait in de
            # achtergrond zodat het venster kan laten zien hoe ver het is.
            from . import voortgang as vg
            from .benodigdheden import zet_alles_klaar

            sleutel = "__opstart__"
            if (vg.stand(sleutel) or {}).get("bezig"):
                self._json({"ok": True, "al_bezig": True})
                return

            # De weging is een schatting op ervaring: ffmpeg 155 MB, Node
            # 50 MB, HyperFrames een npm-installatie, en de browser 170 MB.
            vg.start(sleutel, [
                ("ffmpeg", "Videogereedschap ophalen", 0.34),
                ("node", "Onderdelen voor titels ophalen", 0.16),
                ("titels", "Titelmotor installeren", 0.14),
                ("browser", "Laatste onderdeel ophalen", 0.36),
            ])

            def werk():
                try:
                    zet_alles_klaar(
                        log=lambda *_: None,
                        melden=lambda fase, k=0, t=0: vg.meld(sleutel, fase, k, t),
                    )
                except Exception as e:  # noqa: BLE001
                    vg.mislukt(sleutel, str(e))
                    return
                vg.klaar(sleutel)

            threading.Thread(target=werk, daemon=True).start()
            self._json({"ok": True})
            return

        if pad == "/api/keuze":
            self._keuze(data)
            return

        if pad == "/api/wizard/verwerk":
            self._wizard_verwerk()
            return

        if pad == "/api/wizard/maak":
            self._wizard_maak(data)
            return

        if pad == "/api/kandidaten":
            self._kandidaten(data)
            return

        if pad == "/api/ondertitels":
            self._ondertitels(data)
            return

        self._json({"fout": "onbekende route"}, 404)

    # -- implementaties -------------------------------------------------

    def _project(self) -> None:
        analyse_pad = self.pdir / "analysis.json"
        if not analyse_pad.exists():
            self._json({"fout": "geen analysis.json"}, 404)
            return
        analyse = json.loads(analyse_pad.read_text(encoding="utf-8"))

        # Golfvorm en miniaturen op aanvraag, zodat elk project werkt zonder
        # dat de server ervoor herstart hoeft te worden.
        maak_golfvorm(self.project, log=lambda *_: None)
        maak_thumbnails(self.project, log=lambda *_: None)

        golf = []
        golf_pad = self.pdir / "cache" / "golfvorm.json"
        if golf_pad.exists():
            golf = json.loads(golf_pad.read_text(encoding="utf-8"))["punten"]

        renders = sorted(
            (p.name for p in (self.pdir / "renders").glob("*.mp4")),
            reverse=True,
        )

        # Alleen wat de interface nodig heeft: geen volledige meetreeksen.
        clips = [
            {
                "id": c["id"],
                "bestand": c["bestand"],
                "proxy": c["proxy"],
                "duur": c["duur"],
                "verticaal": c["verticaal"],
                "scene": c.get("scene", 0),
                "opgenomen": c.get("opgenomen"),
                "shots": c["shots"],
            }
            for c in analyse["clips"]
        ]

        muziek = analyse.get("muziek") or {}
        self._json(
            {
                "project": self.project,
                "clips": clips,
                "segmenten": analyse.get("segmenten", []),
                "gewichten": analyse.get("gewichten", {}),
                "stijl": analyse.get("stijl", "actie"),
                "muziek": {
                    "bestand": muziek.get("bestand"),
                    "bpm": muziek.get("bpm"),
                    "duur": muziek.get("duur"),
                    "beats": muziek.get("beats", []),
                    "maten": muziek.get("maten", []),
                    "secties": muziek.get("secties", []),
                    "drops": muziek.get("drops", []),
                },
                "golfvorm": golf,
                "renders": renders,
            }
        )

    def _regie(self, data: dict) -> None:
        from .director import Brief, kies_regisseur

        analyse = json.loads((self.pdir / "analysis.json").read_text(encoding="utf-8"))

        vastgezet = data.get("vastgezet") or []
        brief = Brief(
            tekst=data.get("brief", ""),
            doelduur=data.get("duur"),
            stijl=data.get("stijl", analyse.get("stijl", "actie")),
            vorm=data.get("vorm", "16:9"),
            muziek_start=data.get("muziek_start", 0.0),
            vastgezet=vastgezet,
            uitgesloten=data.get("uitgesloten") or [],
            titel=(data.get("titel") or "").strip(),
            eyebrow=(data.get("eyebrow") or "").strip(),
            ondertitel=(data.get("ondertitel") or "").strip(),
            slottekst=(data.get("slottekst") or "").strip(),
        )
        try:
            voorstel = kies_regisseur(data.get("regisseur", "preset")).stel_voor(analyse, brief)
            voorstel.edl.schrijf(self.pdir / "edl.json")
        except Exception as e:  # noqa: BLE001
            self._json({"fout": str(e)}, 400)
            return
        self._json(
            {
                "ok": True,
                "uitleg": voorstel.uitleg,
                "waarschuwingen": voorstel.waarschuwingen,
                "edl": voorstel.edl.naar_dict(),
            }
        )

    def _upload(self, lengte: int) -> None:
        naam = unquote(self.headers.get("X-Bestandsnaam", ""))
        if not self.project or not naam:
            self._json({"fout": "project of bestandsnaam ontbreekt"}, 400)
            return
        # In stukken lezen: een 4K-clip van 300 MB mag het geheugen niet vullen.
        brokken: list[bytes] = []
        over = lengte
        while over > 0:
            blok = self.rfile.read(min(1 << 20, over))
            if not blok:
                break
            brokken.append(blok)
            over -= len(blok)
        try:
            uit = projecten_mod.bewaar_bestand(self.project, naam, b"".join(brokken))
        except ValueError as e:
            self._json({"fout": str(e)}, 400)
            return
        self._json(uit)

    def _bronnen(self) -> None:
        """Alle bronbestanden met, als de analyse gedraaid is, een oordeel."""
        if not self.project:
            self._json({"fout": "geen project"}, 404)
            return

        meting: dict[str, dict] = {}
        analyse_pad = self.pdir / "analysis.json"
        if analyse_pad.exists():
            try:
                a = json.loads(analyse_pad.read_text(encoding="utf-8"))
                for c in a["clips"]:
                    shots = c.get("shots") or [{}]
                    gem = lambda k: sum(s.get(k, 0) for s in shots) / max(1, len(shots))  # noqa: E731
                    lux = c.get("telemetrie", {}).get("lux") or []
                    meting[c["bestand"]] = {
                        "id": c["id"],
                        "duur": c["duur"],
                        "verticaal": c["verticaal"],
                        "scene": c.get("scene"),
                        "scherpte": round(gem("scherpte"), 3),
                        "belichting": round(gem("belichting"), 3),
                        "beweging": round(gem("beweging"), 3),
                        "shake": round(gem("shake"), 3),
                        "lux": round(sorted(lux)[len(lux) // 2]) if lux else None,
                        "gezichten": max(c.get("telemetrie", {}).get("gezichten") or [0]),
                    }
            except (json.JSONDecodeError, OSError, KeyError):
                meting = {}

        uit = []
        for p in media.vind_bronnen(self.pdir / "bronnen"):
            rij = {"bestand": p.name, "bytes": p.stat().st_size, **meting.get(p.name, {})}
            uit.append(rij)

        muziek = [
            {"bestand": m.name, "bytes": m.stat().st_size}
            for m in media.vind_muziek(self.pdir / "muziek")
        ]
        self._json({"clips": uit, "muziek": muziek, "geanalyseerd": bool(meting)})

    def _kandidaten(self, data: dict) -> None:
        """Andere segmenten die op deze plek in de tijdlijn zouden passen.

        Zo kun je een shot ruilen in plaats van alleen weggooien - de snelste
        manier om je eigen smaak in de montage te krijgen.
        """
        analyse = json.loads((self.pdir / "analysis.json").read_text(encoding="utf-8"))
        nodig = float(data.get("duur", 2.0))
        gebruikt = {(g.get("clip"), round(float(g.get("bron_start", -1)), 2)) for g in data.get("gebruikt", [])}

        clips = {c["id"]: c for c in analyse["clips"]}
        uit = []
        for s in analyse.get("segmenten", []):
            if s["duur"] < nodig - 0.01:
                continue
            if (s["clip"], round(s["start"], 2)) in gebruikt:
                continue
            c = clips.get(s["clip"], {})
            uit.append(
                {
                    "clip": s["clip"],
                    "bestand": c.get("bestand"),
                    "scene": s.get("scene"),
                    "start": s["start"],
                    "duur": s["duur"],
                    "score": s["score"],
                    "verticaal": c.get("verticaal", False),
                    "onderdelen": s.get("onderdelen", {}),
                }
            )
        uit.sort(key=lambda x: -x["score"])
        self._json({"kandidaten": uit[:40], "gewichten": analyse.get("gewichten", {})})

    def _ondertitels(self, data: dict) -> None:
        """Ondertitels maken in de achtergrond en als overlay in de EDL zetten."""
        from . import projecten as pm
        from .edl import EDL as _EDL
        from .graphics import ondertitel_overlay
        from .transcript import maak

        project = self.project
        if not project:
            self._json({"fout": "geen project"}, 400)
            return

        instellingen = {
            "kleur": data.get("kleur", "#2dd4bf"),
            "grootte": data.get("grootte", "normaal"),
            "positie": data.get("positie", "onder"),
            "stijl": data.get("stijl", "karaoke"),
        }

        def werk():
            try:
                pm.zet_bezig(project, "Ondertitels maken…")
                res = maak(project, log=lambda t: pm.zet_bezig(project, f"Ondertitels — {t}"))
                pad = paths.project_dir(project) / "edl.json"
                edl = _EDL.lees(pad)
                edl.overlay = [o for o in edl.overlay if o.soort != "ondertitels"]
                blok = ondertitel_overlay(res["regels"], edl)
                blok.inhoud.update(instellingen)
                edl.overlay.append(blok)
                edl.schrijf(pad)
            except Exception as e:  # noqa: BLE001
                pm.zet_bezig(project, f"FOUT: {e}")
                return
            pm.zet_bezig(project, None)

        threading.Thread(target=werk, daemon=True).start()
        self._json({"ok": True})

    # -- wizard ---------------------------------------------------------
    #
    # De wizard doet in vijf schermen wat de Studio in vijf tabbladen doet.
    # Twee endpoints: inlezen+analyseren (start zodra de bestanden er zijn,
    # zodat het draait terwijl de gebruiker de volgende vragen beantwoordt),
    # en monteren+renderen+nakijken.

    def _wizard_verwerk(self) -> None:
        from . import voortgang as vg
        from .analyse import analyseer
        from .ingest import ingest as _ingest

        project = self.pdir.name
        vg.start(project, vg.WIZARD_FASEN)

        def werk():
            try:
                vg.meld(project, "inlezen", 0, 1)
                _ingest(project, log=lambda *_: None)
                vg.meld(project, "inlezen", 1, 1)
                vg.meld(project, "analyseren", 0, 1)
                analyseer(project, log=lambda *_: None)
                vg.meld(project, "analyseren", 1, 1)
            except Exception as e:  # noqa: BLE001
                vg.mislukt(project, str(e))
                return
            vg.klaar(project)

        threading.Thread(target=werk, daemon=True).start()
        self._json({"ok": True})

    def _wizard_maak(self, data: dict) -> None:
        """Monteren, renderen en nakijken in één beweging."""
        from . import voortgang as vg
        from .director import Brief as _Brief
        from .director import kies_regisseur
        from .graphics import standaard_overlays
        from .render import RenderOpties
        from .render import render as _render
        from .review import review as _review

        project = self.pdir.name
        pdir = self.pdir
        titel = str(data.get("titel") or "").strip()
        vorm = str(data.get("vorm") or "16:9")
        duur = float(data.get("duur") or 75)
        stijl = str(data.get("stijl") or "reis")
        met_internet = bool(data.get("online_plaatsnamen"))

        # Inlezen en analyseren zijn al gebeurd; de balk begint dus verderop,
        # en de tijdschatting rekent vanaf daar.
        vg.start(project, vg.WIZARD_FASEN, vanaf_fase="analyseren")

        def werk():
            try:
                vg.meld(project, "monteren", 0, 1)
                analyse = json.loads((pdir / "analysis.json").read_text(encoding="utf-8"))
                voorstel = kies_regisseur("preset").stel_voor(
                    analyse, _Brief(doelduur=duur, stijl=stijl, vorm=vorm)
                )
                edl = voorstel.edl
                edl.overlay.extend(
                    self._titelblokken(edl, pdir, titel, met_internet=met_internet)
                )
                edl.schrijf(pdir / "edl.json")
                vg.meld(project, "monteren", 1, 1)

                uit = _render(
                    project,
                    opties=RenderOpties(modus="preview"),
                    log=lambda *_: None,
                    melden=lambda fase, k=0, t=0: vg.meld(project, fase, k, t),
                )
                vg.meld(project, "nakijken", 0, 1)
                rapport = _review(project, bestand=uit, log=lambda *_: None).naar_dict()
            except Exception as e:  # noqa: BLE001
                vg.mislukt(project, str(e))
                return
            vg.klaar(project, bestand=uit.name, review=rapport)

        threading.Thread(target=werk, daemon=True).start()
        self._json({"ok": True})

    def _titelblokken(self, edl, pdir: Path, hoofdtitel: str, *, met_internet: bool):
        """Openingstitel plus een titel bij elke nieuwe plek in de montage.

        Valt terug op alleen een openingstitel wanneer er geen locaties in de
        bestanden staan - dan is er niets te vertellen dat we zeker weten.
        """
        from .graphics import standaard_overlays
        from .titels import voorstel as _titelvoorstel
        from .edl import OverlayBlok

        ingest_pad = pdir / "ingest.json"
        clips = {}
        if ingest_pad.exists():
            try:
                clips = {
                    c["id"]: c
                    for c in json.loads(ingest_pad.read_text(encoding="utf-8"))["clips"]
                }
            except (json.JSONDecodeError, KeyError, OSError):
                clips = {}

        gevonden = []
        if clips:
            try:
                gevonden = _titelvoorstel(
                    [b.__dict__ for b in edl.video], clips,
                    hoofdtitel=hoofdtitel, met_internet=met_internet,
                )
            except Exception:  # noqa: BLE001
                gevonden = []

        if not gevonden:
            return standaard_overlays(edl, titel=hoofdtitel) if hoofdtitel else []

        uit = []
        for i, t in enumerate(gevonden):
            uit.append(
                OverlayBlok(
                    id=f"o-titel{i + 1}",
                    soort="titel",
                    tijdlijn_start=t["tijdlijn_start"],
                    duur=t["duur"],
                    inhoud={
                        "titel": t["titel"],
                        "eyebrow": t["eyebrow"],
                        "onder": t["onder"],
                        "positie": "linksonder",
                    },
                )
            )
        return uit

    def _keuze(self, data: dict) -> None:
        """Leg een smaakbeslissing vast: vervangen, verwijderd of vastgezet.

        Faalt dit, dan is dat geen reden om de bewerking zelf te laten
        mislukken - de gebruiker was iets aan het monteren, niet aan het
        trainen. Vandaar dat de fout wel teruggaat maar met status 200.
        """
        from .geheugen import noteer

        try:
            geleerd = noteer(
                self.project,
                str(data.get("soort", "")),
                stijl=str(data.get("stijl") or "actie"),
                weg=data.get("weg"),
                komt=data.get("komt"),
                houd=data.get("houd"),
                index=data.get("index"),
            )
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "fout": str(e)})
            return
        self._json({"ok": True, "geleerd": geleerd})

    def _review(self, data: dict) -> None:
        """Kijk een render na. Duurt op een montage van 80 s ongeveer 10 s.

        Bewust niet in een achtergrondthread: de gebruiker heeft er net op
        geklikt en wil het antwoord, en een halve minuut wachten op een
        voortgangsbalk voor tien seconden werk is onzin.
        """
        from .review import review as _review_fn

        naam = (data or {}).get("bestand")
        bestand = (self.pdir / "renders" / naam) if naam else None
        if bestand and not bestand.exists():
            self._json({"fout": f"{naam} bestaat niet"}, 404)
            return
        try:
            rap = _review_fn(self.project, bestand=bestand, log=lambda *_: None)
        except Exception as e:  # noqa: BLE001
            self._json({"fout": str(e)}, 400)
            return
        self._json(rap.naar_dict())

    def _render(self, data: dict) -> None:
        """Render in de achtergrond en houd de voortgang bij.

        Na afloop meteen `cve review` erover. Dat is precies het moment waarop
        de gebruiker wil weten of het goed ging, en het scheelt hem een tweede
        klik op iets waarvan hij niet weet dat het bestaat.
        """
        from . import voortgang as vg
        from .render import RenderOpties
        from .render import render as _render

        modus = "eind" if data.get("eind") else "preview"
        tot = data.get("tot")
        project = self.project
        pdir = self.pdir

        vg.start(project)

        def werk():
            try:
                uit = _render(
                    project,
                    opties=RenderOpties(modus=modus, tot=tot),
                    log=lambda *_: None,
                    melden=lambda fase, k=0, t=0: vg.meld(project, fase, k, t),
                )
            except Exception as e:  # noqa: BLE001
                vg.mislukt(project, str(e))
                return

            rapport = None
            # Een snelle voorvertoning van 15 s nakijken heeft geen zin: die
            # is per definitie korter dan de EDL en zou alleen maar afgaan.
            if not tot:
                try:
                    vg.meld(project, "nakijken", 0, 1)
                    from .review import review as _review

                    rapport = _review(project, bestand=uit, log=lambda *_: None).naar_dict()
                except Exception as e:  # noqa: BLE001
                    rapport = {"fout": str(e), "bevindingen": []}
            vg.klaar(project, bestand=str(uit.relative_to(pdir)), review=rapport)

        threading.Thread(target=werk, daemon=True).start()
        self._json({"ok": True, "gestart": "snel" if tot else modus})


def start(project: str = "", *, poort: int = 8420, open_browser: bool = True, log=print) -> None:
    """Start de Studio. Zonder project opent het startscherm."""
    paths.PROJECTEN.mkdir(parents=True, exist_ok=True)

    if project:
        pdir = paths.project_dir(project)
        if (pdir / "ingest.json").exists():
            log("Miniaturen en golfvorm voorbereiden...")
            maak_thumbnails(project, log=log)
            maak_golfvorm(project, log=log)

    handler = partial(StudioHandler)
    StudioHandler.start_project = project

    server = StudioServer(("127.0.0.1", poort), handler)
    url = f"http://127.0.0.1:{poort}/" + (f"studio?project={project}" if project else "")
    log(f"\nStudio draait op {url}\nStop met Ctrl-C.\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nGestopt.")
        server.shutdown()
