/* ==================================================================
   Themakeuze — gedeeld door start, wizard en Studio.

   Drie standen: volg het systeem, altijd licht, altijd donker. De keuze
   staat in localStorage, dus hij geldt ook op de volgende pagina en na
   een herstart.

   Let op de volgorde: het attribuut wordt gezet in de <head>, vóórdat er
   iets getekend is. Doe je dat pas als de pagina klaar is, dan zie je bij
   elke navigatie een flits van het verkeerde thema.
================================================================== */
(function () {
  const SLEUTEL = 'cve-thema';
  const geldig = ['auto', 'licht', 'donker'];

  function huidig() {
    try {
      const v = localStorage.getItem(SLEUTEL);
      return geldig.includes(v) ? v : 'auto';
    } catch { return 'auto'; }
  }

  function zet(thema) {
    const t = geldig.includes(thema) ? thema : 'auto';
    // "auto" betekent: geen attribuut, dan volgt `color-scheme: light dark`
    // vanzelf de voorkeur van het besturingssysteem.
    if (t === 'auto') document.documentElement.removeAttribute('data-thema');
    else document.documentElement.setAttribute('data-thema', t);
    try { localStorage.setItem(SLEUTEL, t); } catch { /* privémodus */ }
    document.querySelectorAll('.thema button').forEach(b =>
      b.classList.toggle('aan', b.dataset.thema === t));
  }

  // Meteen toepassen, nog voor de eerste verf.
  zet(huidig());

  const IKOON = {
    auto: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.2"/><path d="M8 2.8v10.4" /><path d="M8 3a5 5 0 010 10z" fill="currentColor" stroke="none"/></svg>',
    licht: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="3.1"/><path d="M8 1.2v1.6M8 13.2v1.6M1.2 8h1.6M13.2 8h1.6M3.2 3.2l1.1 1.1M11.7 11.7l1.1 1.1M12.8 3.2l-1.1 1.1M4.3 11.7l-1.1 1.1"/></svg>',
    donker: '<svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor"><path d="M13.4 9.6A5.8 5.8 0 016.4 2.6a.6.6 0 00-.8-.7 6.6 6.6 0 108.5 8.5.6.6 0 00-.7-.8z"/></svg>',
  };
  const TITEL = { auto: 'Volg het systeem', licht: 'Licht', donker: 'Donker' };

  /* Zet de schakelaar in een element met `data-thema-schakelaar`. */
  function bouw() {
    document.querySelectorAll('[data-thema-schakelaar]').forEach(doel => {
      if (doel.querySelector('.thema')) return;
      const groep = document.createElement('div');
      groep.className = 'thema';
      groep.setAttribute('role', 'group');
      groep.setAttribute('aria-label', 'Weergave');
      groep.innerHTML = geldig.map(t =>
        `<button type="button" data-thema="${t}" title="${TITEL[t]}"
           aria-label="${TITEL[t]}">${IKOON[t]}</button>`).join('');
      groep.querySelectorAll('button').forEach(b =>
        b.onclick = () => zet(b.dataset.thema));
      doel.appendChild(groep);
      zet(huidig());
    });
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', bouw);
  else bouw();

  window.cveThema = { zet, huidig, bouw };
})();

/* ==================================================================
   Eenmalig klaarzetten

   BeatCut heeft ffmpeg nodig en dat zit bewust niet in de app (zie
   `engine/cve/benodigdheden.py` voor waarom). Bij de eerste start halen
   we het zelf op — de gebruiker hoeft niets te weten, te zoeken of te
   installeren. Hij ziet één scherm met een balk en daarna werkt alles.
================================================================== */
(function () {
  async function kijk() {
    let d;
    try {
      const r = await fetch('/api/benodigdheden');
      d = await r.json();
    } catch { return; }
    if (!d || d.compleet) return;    // alles aanwezig, niets te doen
    scherm();
    try {
      await fetch('/api/benodigdheden/haal', { method: 'POST' });
    } catch { /* de lus meldt het wel */ }
    volg();
  }

  function scherm() {
    if (document.getElementById('opstart')) return;
    const el = document.createElement('div');
    el.id = 'opstart';
    el.innerHTML = `
      <div class="opstartkaart">
        <h2>Even klaarzetten</h2>
        <p>BeatCut haalt op wat hij nodig heeft om video's te maken.
           Dat gebeurt één keer en duurt een paar minuten. Daarna hoef je
           nooit meer iets te installeren.</p>
        <div class="vbalk"><i id="opstartbalk" style="width:4%"></i></div>
        <p class="opstartklein" id="opstarttekst">Bezig…</p>
      </div>`;
    document.body.appendChild(el);
  }

  function volg() {
    const lus = setInterval(async () => {
      let v;
      try {
        const r = await fetch('/api/voortgang?sleutel=__opstart__');
        v = await r.json();
      } catch { return; }
      const balk = document.getElementById('opstartbalk');
      const tekst = document.getElementById('opstarttekst');
      if (balk) balk.style.width = Math.max(4, v.percentage || 0) + '%';
      if (tekst && v.bezig) tekst.textContent =
        (v.tekst || 'Bezig…') + ' — ' + Math.round(v.percentage || 0) + '%';
      if (v.bezig) return;
      clearInterval(lus);
      if (v.fase === 'fout') {
        if (tekst) {
          tekst.innerHTML = `Het ophalen lukte niet: ${v.fout || 'onbekende fout'}.<br>
            Je kunt het zelf installeren met <code>brew install ffmpeg</code>
            en daarna dit venster herladen.`;
          tekst.style.color = 'var(--fout)';
        }
        return;
      }
      if (balk) balk.style.width = '100%';
      if (tekst) tekst.textContent = 'Klaar. Een moment…';
      setTimeout(() => location.reload(), 900);
    }, 900);
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', kijk);
  else kijk();
})();

/* ==================================================================
   Nieuwe versie beschikbaar?

   Eén keer per dag vraagt de engine het aan GitHub; hier tonen we het
   alleen. Bewust een klein balkje onderin en geen popup: je zit midden
   in een montage en een update is nooit dringend.
================================================================== */
(function () {
  const WEG = 'cve-update-weg';

  async function kijk() {
    let d;
    try {
      const r = await fetch('/api/update');
      d = await r.json();
    } catch { return; }
    if (!d || !d.nieuwer || !d.nieuwste) return;
    // Weggeklikt voor deze versie? Dan niet blijven zeuren.
    try { if (localStorage.getItem(WEG) === d.nieuwste) return; } catch { /* leeg */ }
    toon(d);
  }

  function toon(d) {
    const balk = document.createElement('div');
    balk.className = 'updatebalk';
    balk.innerHTML =
      `<span>Versie <b>${d.nieuwste}</b> is beschikbaar — je hebt ${d.huidig}.</span>
       <a href="${d.url}" target="_blank" rel="noopener">Bekijken</a>
       <button type="button" aria-label="Sluiten">×</button>`;
    balk.querySelector('button').onclick = () => {
      try { localStorage.setItem(WEG, d.nieuwste); } catch { /* leeg */ }
      balk.remove();
    };
    document.body.appendChild(balk);
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', kijk);
  else kijk();
})();
