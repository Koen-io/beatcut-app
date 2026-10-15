"""De tijdschatting van het verwerken: klopt "nog ±" met de werkelijkheid?

Koens eis is dat het getal klopt, niet dat er een getal staat. Deze tests
draaien daarom met een nepklok: dan is de echte eindtijd bekend en valt de
voorspelling ernaast te leggen.
"""

from __future__ import annotations

import json

import pytest

from cve import doorvoer


class Klok:
    """Een klok die alleen loopt als de test hem laat lopen."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tik(self, seconden: float) -> None:
        self.t += seconden


@pytest.fixture
def klok(monkeypatch):
    k = Klok()
    monkeypatch.setattr(doorvoer.time, "monotonic", k)
    return k


@pytest.fixture
def lege_steun(tmp_path, monkeypatch):
    """Een verse steunmap, zodat een eerder gemeten tarief niet meelekt."""
    monkeypatch.setenv("BEATCUT_STEUN", str(tmp_path / "steun"))
    return tmp_path / "steun"


# Hoeveel boekingen er nodig zijn voordat het tarief van déze run het helemaal
# overgenomen heeft: eerst het ijkpunt, daarna de overgang. Zie `_Fase.tarief`
# en `Meter._tarief`.
VOL = doorvoer.MIN_PUNTEN + doorvoer.OVERGANG


def _doe(meter: doorvoer.Meter, klok: Klok, fase: str, bron: float, tarief: float) -> None:
    """Werk `bron` seconden bronvideo weg met `tarief` bron-sec per wandkloksec."""
    klok.tik(bron / tarief)
    meter.boek(fase, bron)


# ---------------------------------------------------------------- schatten…


def test_zonder_meting_staat_er_geen_getal(klok, lege_steun):
    """De eerste keer op een machine valt er niets te beloven."""
    m = doorvoer.Meter(["inlezen", "analyseren"])
    m.klus(300.0)
    m.plan("inlezen", 300.0)
    assert m.resterend() is None
    assert m.aandeel() is None

    # Eén meting is nog geen tarief: MIN_PUNTEN staat op 3.
    _doe(m, klok, "inlezen", 30.0, 4.0)
    assert m.resterend() is None


def test_na_genoeg_metingen_komt_er_een_getal(klok, lege_steun):
    """Eén boeking ná het ijkpunt is genoeg voor een eerste getal."""
    m = doorvoer.Meter(["inlezen"])
    m.klus(300.0)
    m.plan("inlezen", 300.0)
    for _ in range(doorvoer.MIN_PUNTEN + 1):
        _doe(m, klok, "inlezen", 30.0, 4.0)
    assert m.resterend() is not None


# ------------------------------------------------- klopt de voorspelling?


def test_de_voorspelling_komt_uit_bij_een_vaste_doorvoer(klok, lege_steun):
    """1200 s bronvideo op 4 bron-sec per wandkloksec = 300 s.

    Eerst de meting laten rijpen: tot `VOL` boekingen weegt de startwaarde nog
    mee (zie `_tarief`). Daarna hoort het getal gewoon te kloppen.
    """
    m = doorvoer.Meter(["inlezen"])
    m.klus(100.0 * VOL * 2)
    m.plan("inlezen", 100.0 * VOL * 2)
    for _ in range(VOL):
        _doe(m, klok, "inlezen", 100.0, 4.0)

    assert m.verstreken == pytest.approx(VOL * 25.0, abs=0.1)
    assert m.resterend() == pytest.approx(VOL * 25.0, abs=2.0)
    assert m.aandeel() == pytest.approx(0.5, abs=0.01)


def test_de_startwaarde_weegt_mee_tot_de_meting_gerijpt_is(klok, lege_steun):
    """Een jonge meting ziet maar een paar clips, en die kunnen kort of lang zijn.

    Halverwege de overgang is het tarief daarom half de meting en half de
    startwaarde. Zonder die overgang sprong "nog ±" bij de vijfde clip van 9
    naar 13 seconden (gemeten 04-10-2026 op de 21 testclips).
    """
    m = doorvoer.Meter(["inlezen"])
    m.klus(4000.0)
    m.plan("inlezen", 4000.0)
    for _ in range(doorvoer.MIN_PUNTEN + doorvoer.OVERGANG // 2):
        _doe(m, klok, "inlezen", 100.0, 4.0)
    half = (4.0 + doorvoer.AANNAME["inlezen"]) / 2
    over = 4000.0 - 100.0 * (doorvoer.MIN_PUNTEN + doorvoer.OVERGANG // 2)
    assert m.resterend() == pytest.approx(over / half, abs=3.0)


def test_de_voorspelling_overleeft_de_hele_rit(klok, lege_steun):
    """Voorspelde eindtijd naast de echte, bij elke stap van een hele klus.

    De maat is de eindtijd en niet de fout op de resterende tijd. Dat tweede
    getal is onbruikbaar hard aan het eind: "nog 1 s" bij een halve seconde te
    gaan zit er 100 % naast en is praktisch goed.

    Deze machine haalt 4 bron-sec/s waar de startwaarde 13 aanneemt — ruim drie
    keer zo langzaam, het slechtste geval. Tot de meting gerijpt is (`VOL`
    boekingen) weegt die startwaarde mee en zit de voorspelling er dus naast;
    dat is geen fout maar precies waar "schatten…" en de overgang voor zijn.
    Vanaf daar hoort het te kloppen, en dat is wat hier gecontroleerd wordt.
    """
    m = doorvoer.Meter(["inlezen"])
    m.klus(3000.0)
    m.plan("inlezen", 3000.0)
    duur = 3000.0 / 4.0
    fouten = []
    for stap in range(100):
        _doe(m, klok, "inlezen", 30.0, 4.0)
        rest = m.resterend()
        if rest is None or stap + 1 < VOL:
            continue
        fouten.append(abs((m.verstreken + rest) - duur) / duur)
    assert fouten, "er is nooit een getal gegeven"
    assert max(fouten) < 0.05, f"grootste afwijking {max(fouten):.1%}"
    assert m.resterend() == 0


def test_een_fase_die_nog_niet_begonnen_is_telt_mee(klok, lege_steun):
    """Zonder dit belooft de balk tijdens het inlezen de analyse weg.

    De klus is 300 s bronvideo. Inlezen gaat op 4 bron-sec/s (75 s), analyseren
    op de aanname van 43 (7 s). Op het moment dat inlezen klaar is hoort er dus
    nog ongeveer 7 s te staan, niet 0.
    """
    m = doorvoer.Meter(["inlezen", "analyseren"])
    m.klus(300.0)
    m.plan("inlezen", 300.0)
    for _ in range(VOL):
        _doe(m, klok, "inlezen", 300.0 / VOL, 4.0)

    rest = m.resterend()
    verwacht = 300.0 / doorvoer.AANNAME["analyseren"]
    assert rest == pytest.approx(verwacht, abs=1.0)
    assert m.aandeel() == pytest.approx(75.0 / (75.0 + verwacht), abs=0.01)


def test_de_balk_gaat_nooit_achteruit_en_staat_vol_als_de_tijd_nul_is(klok, lege_steun):
    """Balk en getal komen uit één som, dus ze kunnen niet uit elkaar lopen.

    Twee dingen die daaruit moeten volgen en die een gebruiker ziet: de balk
    gaat nooit terug (dat leest als een fout — zelfde regel als in
    voortgang.py), en "vol" betekent ook echt "nul te gaan". Een balk op 100 %
    met "nog 3 s" eronder is precies het soort tegenstrijdigheid waardoor
    niemand de balk meer gelooft.
    """
    m = doorvoer.Meter(["inlezen", "analyseren"])
    m.klus(1200.0)
    m.plan("inlezen", 1200.0)
    vorige = 0.0
    for _ in range(12):  # 12 x 100 s = de hele geplande 1200 s
        _doe(m, klok, "inlezen", 100.0, 3.0)
        rest, deel = m.resterend(), m.aandeel()
        if rest is None or deel is None:
            continue
        assert deel >= vorige, f"balk ging terug: {vorige:.3f} -> {deel:.3f}"
        vorige = deel
        assert (deel >= 1.0) == (rest == 0)

    m.plan("analyseren", 1200.0)
    for _ in range(VOL):
        _doe(m, klok, "analyseren", 1200.0 / VOL, 40.0)
    assert m.aandeel() == pytest.approx(1.0, abs=0.01)
    assert m.resterend() == 0


# ------------------------------------------------------- wachtrij groeit


def test_clips_erbij_laten_de_schatting_meegroeien(klok, lege_steun):
    """Koens eis: herbereken bij extra video's, niet opnieuw beginnen."""
    m = doorvoer.Meter(["inlezen"])
    m.klus(100.0 * (VOL + 2))
    m.plan("inlezen", 100.0 * (VOL + 2))
    for _ in range(VOL):
        _doe(m, klok, "inlezen", 100.0, 4.0)
    voor = m.resterend()
    assert voor == pytest.approx(200.0 / 4.0, abs=3.0)  # 200 s bron over op 4/s

    # Er komen 1200 s bronvideo bij (tweede ronde van de engine).
    m.klus(1200.0)
    m.plan("inlezen", 1200.0)
    na = m.resterend()
    assert na is not None and na > voor
    assert na == pytest.approx((200.0 + 1200.0) / 4.0, abs=8.0)


# -------------------------------------------------------- tarief bewaren


def test_het_gemeten_tarief_gaat_mee_naar_de_volgende_keer(klok, lege_steun):
    m = doorvoer.Meter(["inlezen"])
    m.klus(400.0)
    m.plan("inlezen", 400.0)
    for _ in range(5):
        _doe(m, klok, "inlezen", 80.0, 4.0)
    bewaard = m.bewaar()
    assert bewaard["inlezen"] == pytest.approx(4.0, abs=0.2)

    opgeslagen = json.loads((lege_steun / doorvoer.BESTAND).read_text(encoding="utf-8"))
    assert opgeslagen["inlezen"] == pytest.approx(4.0, abs=0.2)

    # De tweede run mag meteen een getal geven: deze machine is bekend.
    tweede = doorvoer.Meter(["inlezen"])
    tweede.klus(400.0)
    tweede.plan("inlezen", 400.0)
    assert tweede.resterend() == pytest.approx(100.0, abs=5.0)


def test_een_piepkleine_ronde_bewaart_geen_tarief(klok, lege_steun):
    """Twee clips van een seconde meten de ruis, niet de machine."""
    m = doorvoer.Meter(["inlezen"])
    m.klus(4.0)
    m.plan("inlezen", 4.0)
    for _ in range(4):
        _doe(m, klok, "inlezen", 1.0, 4.0)
    assert m.bewaar() == {}
    assert not (lege_steun / doorvoer.BESTAND).exists()


def test_rommel_in_het_bewaarbestand_is_geen_crash(lege_steun):
    lege_steun.mkdir(parents=True, exist_ok=True)
    (lege_steun / doorvoer.BESTAND).write_text("{niet json", encoding="utf-8")
    assert doorvoer.lees_tarieven() == {}
    (lege_steun / doorvoer.BESTAND).write_text('{"inlezen": "snel", "x": -1}', encoding="utf-8")
    assert doorvoer.lees_tarieven() == {}


# --------------------------------------- wat de tegenlezing van 04-10 vond


def test_de_balk_staat_niet_vol_als_er_nog_werk_bij_komt(klok, lege_steun):
    """Codex, 04-10-2026: `aandeel: 1.0` naast `resterend: 10`.

    De klink die de balk vooruit houdt bleef op 100 % staan toen er een tweede
    ronde bij geboekt werd. Een volle balk met "nog tien seconden" eronder is
    precies de tegenstrijdigheid waardoor niemand de balk nog gelooft.
    """
    m = doorvoer.Meter(["inlezen"])
    m.klus(400.0)
    m.plan("inlezen", 400.0)
    for _ in range(VOL):
        _doe(m, klok, "inlezen", 400.0 / VOL, 4.0)
    assert m.aandeel() == pytest.approx(1.0, abs=0.01)
    assert m.resterend() == 0

    m.klus(400.0)
    m.plan("inlezen", 400.0)
    deel, rest = m.aandeel(), m.resterend()
    assert rest is not None and rest > 0
    assert deel is not None and deel < 0.9, f"balk op {deel:.0%} terwijl er nog {rest} s te gaan is"


def test_een_tweede_ronde_bederft_het_bewaarde_tarief_niet(klok, lege_steun):
    """Codex, 04-10-2026: `bewaar()` telde de tijd van ándere fasen mee.

    `f.begon` bleef op het begin van ronde één staan terwijl `f.laatst`
    doorschoof naar ronde twee, dus de analyse en het afronden ertussen gingen
    als inleestijd de boeken in. Het bewaarde tarief kwam daardoor een factor
    te laag uit, en de volgende run voorspelde slechter dan deze.
    """
    m = doorvoer.Meter(["inlezen", "analyseren"])
    m.klus(2000.0)
    # Ronde 1: beide fasen op precies 10 bron-sec per wandkloksec.
    for fase in ("inlezen", "analyseren"):
        m.plan(fase, 1000.0)
        for _ in range(5):
            _doe(m, klok, fase, 200.0, 10.0)
    # Ronde 2: idem. Tussen de twee inleesrondes zat de hele analyse.
    for fase in ("inlezen", "analyseren"):
        m.plan(fase, 1000.0)
        for _ in range(5):
            _doe(m, klok, fase, 200.0, 10.0)

    bewaard = m.bewaar()
    for fase in ("inlezen", "analyseren"):
        assert bewaard[fase] == pytest.approx(10.0, rel=0.1), f"{fase}: {bewaard[fase]}"
