/* ==================================================================
   De twintig titelstijlen — tekst, maat en animatie.

   Eén compositie, twintig varianten. De vormgeving komt als `spec` binnen
   (één regel uit `styles/titels/titels.json`), de tekst uit de titelbron
   (plaats, datum, hoogte). Hier staat alleen wat code moet zijn: welk stuk
   tekst een stijl laat zien, hoe groot het wordt, en hoe het beweegt.

   Drie dingen om in de gaten te houden (projectgeheugen/hyperframes-titels.md):
   - `data-duration` staat in de HTML; graphics._op_maat() zet hem goed.
   - clips die JavaScript aanmaakt bestaan niet voor de renderer.
   - het wortelelement mag zelf geen class="clip" dragen.
================================================================== */
(function () {
  'use strict';

  var v = (window.__hyperframes && window.__hyperframes.getVariables()) || {};
  var root = document.getElementById('root');
  var B = Number(root.getAttribute('data-width')) || 1920;
  var H = Number(root.getAttribute('data-height')) || 1080;
  var duur = Math.max(1.2, Number(v.duur) || 4);
  var voorbeeld = Number(v.voorbeeld) === 1;

  var spec = {};
  try { spec = JSON.parse(v.spec || '{}') || {}; } catch (e) { spec = {}; }

  var kader = document.getElementById('kader');
  var kaart = document.getElementById('kaart');
  var titelEl = document.getElementById('titel');
  var vulEl = document.getElementById('vul');
  var onderEl = document.getElementById('onder');
  var eyebrowEl = document.getElementById('eyebrow');
  var bovenEl = document.getElementById('boven');
  var lijnEl = document.getElementById('lijn');

  /* ---------------- tekst: welk stuk van de titelbron ---------------- */

  var titel = String(v.titel || '').trim();
  var eyebrow = String(v.eyebrow || '').trim();
  var onder = String(v.onder || '').trim();
  var datum = String(v.datum || '').trim();
  var coords = String(v.coords || '').trim();

  /* Displaytype van 200 px wordt onleesbaar met een plaatsnaam van drie
     woorden. De stijlen die daarop gebouwd zijn nemen het eerste woord —
     "Garmisch-Partenkirchen" wordt "Garmisch". */
  function eersteWoord(s) {
    var m = String(s).split(/[\s\-–—/,]+/).filter(Boolean);
    return m.length ? m[0] : s;
  }

  function stapelRegels(s) {
    var d = String(s).split(/[\s\-–—/]+/).filter(Boolean);
    return d.length ? d : [s];
  }

  var hoofd = titel || 'Titel';
  var regels = [hoofd];
  var modus = spec.modus || 'heel';

  if (modus === 'eerste') {
    hoofd = eersteWoord(titel) || 'Titel';
    regels = [hoofd];
  } else if (modus === 'stapel') {
    regels = stapelRegels(titel);
    hoofd = regels.join('\n');
  } else if (modus === 'getal') {
    // Zonder hoogte in de GPS-data valt deze stijl terug op de titel; een
    // lege overlay is erger dan een andere tekst (review: overlay_leeg).
    hoofd = onder || titel || 'Titel';
    regels = [hoofd];
  } else if (modus === 'datum') {
    hoofd = datum || eyebrow || titel || 'Titel';
    regels = [hoofd];
  }

  /* De ondertekst is wat er aan gemeten feiten óver is. */
  var subdelen = [];
  if (modus === 'getal') {
    subdelen = [titel || 'boven zeeniveau'];
  } else if (modus === 'datum') {
    subdelen = [];
  } else if (spec.id === 'coords' && coords) {
    // Daar is deze stijl voor: de plek in cijfers, met de hoogte erachter.
    subdelen = onder ? [coords, onder] : [coords];
  } else {
    if (eyebrow) subdelen.push(eyebrow);
    if (onder) subdelen.push(onder);
  }
  var sub = subdelen.join(' · ');

  /* ---------------- vormgeving ---------------- */

  var accent = v.kleur || '#2dd4bf';
  var tekstkleur = v.tekstkleur || '#ffffff';
  var SCHADUW = '0 .03em .28em rgba(0,0,0,.85), 0 0 .8em rgba(0,0,0,.4)';

  kaart.classList.add('stijl-' + (spec.id || 'onderbalk'));
  kader.style.justifyContent = spec.h || 'flex-start';
  kader.style.alignItems = spec.v || 'flex-end';
  kader.style.setProperty('--marge-h', (B * 0.055).toFixed(1) + 'px');
  kader.style.setProperty('--marge-v', (H * 0.08).toFixed(1) + 'px');
  if (spec.balk) kader.classList.add('met-balk');

  kaart.style.setProperty('--accent', accent);
  kaart.style.setProperty('--tekst', spec.kleur || tekstkleur);
  kaart.style.setProperty('--lijnkleur', tekstkleur);
  // Eyebrow, bovenregel en ondertekst staan buiten een eventueel vlak en
  // houden dus de gewone tekstkleur: zwarte letters op een pil zijn goed,
  // zwarte letters eronder op het beeld niet.
  kaart.style.setProperty('--subtekst', tekstkleur);
  kaart.style.setProperty('--schaduw', spec.schaduw || SCHADUW);
  kaart.style.setProperty('--padding', spec.padding || '0');
  kaart.style.setProperty('--rond', spec.rond || '0');
  kaart.style.setProperty('--contour', spec.contour || '0.02em');
  var vlak = spec.vlak === 'ACCENT' ? accent : (spec.vlak || 'transparent');
  kaart.style.setProperty('--vlak', vlak);
  kaart.style.fontFamily = spec.font || "'Geist', sans-serif";
  kaart.style.fontWeight = spec.gewicht || 600;
  kaart.style.fontStyle = spec.cursief || 'normal';
  kaart.style.textTransform = spec.transform || 'none';
  kaart.style.letterSpacing = spec.spatiering || '0';
  kaart.style.lineHeight = spec.regelhoogte || 1.05;
  kaart.style.textAlign = spec.uitlijning || 'left';
  titelEl.style.whiteSpace = regels.length > 1 ? 'pre-wrap' : 'nowrap';
  if (spec.subfont) onderEl.style.fontFamily = spec.subfont;
  if (spec.subfont) bovenEl.style.fontFamily = spec.subfont;

  /* ---------------- tekst in de DOM ---------------- */

  function schrijf(el, tekst) {
    el.textContent = tekst;
    el.style.display = tekst ? 'block' : 'none';
  }

  titelEl.textContent = hoofd;
  vulEl.textContent = hoofd;
  if (spec.sub) schrijf(onderEl, sub);
  if (spec.boven) schrijf(bovenEl, 'Hoofdstuk ' + (Number(v.nummer) || 1));
  if (spec.lijn) lijnEl.style.display = 'block';

  /* Opsplitsen gebeurt vóór het meten: losse spans nemen iets meer ruimte dan
     doorlopende tekst, en anders past de gemeten maat net niet. */
  function splits(soort) {
    var stukken = soort === 'letter'
      ? hoofd.split('')
      : (soort === 'regel' ? regels : hoofd.split(/(\s+)/));
    titelEl.textContent = '';
    var uit = [];
    stukken.forEach(function (s) {
      if (soort !== 'regel' && /^\s+$/.test(s)) {
        titelEl.appendChild(document.createTextNode(s));
        return;
      }
      var span = document.createElement('span');
      span.className = soort === 'letter' ? 'letter' : (soort === 'regel' ? 'regel' : 'woord');
      span.textContent = s === ' ' ? ' ' : s;
      titelEl.appendChild(span);
      uit.push(span);
    });
    return uit;
  }

  var delen = [];
  if (spec.id === 'letters') delen = splits('letter');
  else if (spec.id === 'slam' || spec.id === 'karaoke') delen = splits('woord');
  else if (spec.id === 'gestapeld') delen = splits('regel');

  /* De maat meten mag pas als de letters er zijn. Meet je met het
     vervangende systeemlettertype, dan is de uitkomst te smal en steekt een
     lange plaatsnaam alsnog buiten beeld — dat was precies wat "Hoofdstuk"
     deed. De renderer wacht gewoon tot `window.__timelines` er staat. */
  function afmaken() {
    /* ---------------- maat: schalen met de korte zijde, dan inpassen -------- */

    // De maten in de catalogus zijn pixels op een canvas van 405 px hoog — de
    // maat waarop het ontwerp getekend is.
    var schaal = Math.min(B, H) / 405;
    var basis = (spec.grootte || 30) * schaal;
    var veiligB = B * (1 - 2 * 0.055);
    var veiligH = H * (1 - 2 * 0.08);

    // Daarna nog krimpen als het niet past. Zonder deze stap valt een lange
    // plaatsnaam in 9:16 gewoon buiten beeld.
    for (var i = 0; i < 12; i++) {
      kaart.style.fontSize = basis.toFixed(2) + 'px';
      if (spec.sub) onderEl.style.fontSize = ((spec.subgrootte || 14) * schaal).toFixed(2) + 'px';
      if (spec.boven) bovenEl.style.fontSize = ((spec.subgrootte || 13) * schaal).toFixed(2) + 'px';
      if (spec.lijn) lijnEl.style.width = (basis * 1.4).toFixed(1) + 'px';
      var br = Math.max(kaart.scrollWidth, titelEl.scrollWidth);
      var ho = kaart.scrollHeight;
      if (br <= veiligB && ho <= veiligH) break;
      basis *= Math.min(veiligB / Math.max(br, 1), veiligH / Math.max(ho, 1)) * 0.97;
    }

    /* ---------------- animatie per stijl ---------------- */

    var tl = gsap.timeline({ paused: true });
    var uit = Math.max(0.6, duur - 0.55);
    var em = basis;

    function scramble(el, tekst, charset, van, lengte) {
      var staat = { p: 0 };
      tl.to(staat, {
        p: 1, duration: lengte, ease: 'none',
        onUpdate: function () {
          var n = Math.round(staat.p * tekst.length);
          var s = tekst.slice(0, n);
          for (var k = n; k < tekst.length; k++) {
            s += tekst[k] === ' ' ? ' ' : charset[Math.floor(Math.random() * charset.length)];
          }
          el.textContent = s;
        }
      }, van);
    }

    var ANIMATIES = {
      onderbalk: function () {
        tl.from('#balk', { scaleX: 0, duration: .5, ease: 'power3.out' }, 0)
          .from('#kaart', { opacity: 0, y: em * .5, duration: .55, ease: 'power3.out' }, .18);
      },
      slam: function () {
        tl.from(delen, {
          opacity: 0, scale: 2.4, duration: .42, ease: 'back.out(2.2)', stagger: .12
        }, 0);
      },
      letters: function () {
        tl.from(delen, {
          opacity: 0, yPercent: 110, rotateX: -70, transformOrigin: '50% 100%',
          duration: .5, ease: 'power3.out', stagger: .035
        }, 0);
      },
      masker: function () {
        tl.fromTo('.titelrij', { clipPath: 'inset(0 100% 0 0)' },
          { clipPath: 'inset(0 0% 0 0)', duration: .55, ease: 'power3.inOut' }, 0);
      },
      coords: function () {
        tl.from('#kaart', { opacity: 0, duration: .4 }, 0)
          .from('#lijn', { scaleX: 0, duration: .5, ease: 'power2.inOut' }, .1);
        // De cijfers in de ondertekst rollen naar hun waarde.
        if (sub) scramble(onderEl, sub, '0123456789', .2, .6);
      },
      hand: function () {
        tl.fromTo('.titelrij', { clipPath: 'inset(-20% 100% -20% 0)' },
          { clipPath: 'inset(-20% 0% -20% 0)', duration: .95, ease: 'power1.inOut' }, 0);
      },
      redactie: function () {
        tl.from('#kaart', {
          opacity: 0, letterSpacing: '0.34em', duration: .9, ease: 'power2.out'
        }, 0);
      },
      glitch: function () {
        tl.fromTo('#kaart', { opacity: 0 }, { opacity: 1, duration: .08, ease: 'steps(1)' }, 0)
          .to('#kaart', { opacity: .2, duration: .06 }, .14)
          .to('#kaart', { opacity: 1, duration: .06 }, .22);
        for (var k = 0; k < 6; k++) {
          tl.to('#titel', {
            x: (k % 2 ? -1 : 1) * em * (0.06 - k * 0.009), duration: .05, ease: 'steps(1)'
          }, .3 + k * .07);
        }
        tl.to('#titel', { x: 0, duration: .08 }, .75);
      },
      neon: function () {
        // Een buis die aanslaat: een paar keer kort aan en uit, dan vol.
        tl.set('#kaart', { opacity: .1 }, 0);
        [[.04, 1], [.10, .12], [.17, 1], [.23, .15], [.31, 1], [.37, .2]]
          .forEach(function (stap) {
            tl.to('#kaart', { opacity: stap[1], duration: .04, ease: 'steps(1)' }, stap[0]);
          });
        tl.to('#kaart', { opacity: 1, duration: .3, ease: 'power2.out' }, .45);
      },
      karaoke: function () {
        tl.from('#kaart', { opacity: 0, y: em * .4, duration: .4, ease: 'power2.out' }, 0);
        delen.forEach(function (w, k) {
          w.style.opacity = '.45';
          tl.to(w, { opacity: 1, color: accent, duration: .22, ease: 'power1.out' },
            .3 + k * .22);
        });
      },
      teller: function () {
        var m = /(-?[\d.,]+)/.exec(hoofd);
        tl.from('#kaart', { opacity: 0, y: em * .3, duration: .45, ease: 'power3.out' }, 0);
        if (!m) return;
        var doel = parseFloat(m[1].replace(',', '.'));
        var staat = { n: 0 };
        tl.to(staat, {
          n: doel, duration: .9, ease: 'power2.out',
          onUpdate: function () {
            titelEl.textContent = hoofd.replace(m[1], String(Math.round(staat.n)));
          }
        }, .1);
      },
      pin: function () {
        tl.from('#kaart', {
          opacity: 0, y: -em * 1.2, duration: .7, ease: 'bounce.out'
        }, 0).from('#lijn', { scaleX: 0, duration: .55, ease: 'power2.inOut' }, .5);
      },
      datum: function () {
        titelEl.textContent = '';
        var staat = { p: 0 };
        tl.to(staat, {
          p: 1, duration: Math.min(1.1, hoofd.length * .09), ease: 'none',
          onUpdate: function () {
            var n = Math.round(staat.p * hoofd.length);
            titelEl.textContent = hoofd.slice(0, n) + (staat.p < 1 && n % 2 === 0 ? '_' : '');
          },
          onComplete: function () { titelEl.textContent = hoofd; }
        }, 0);
      },
      decoder: function () {
        tl.from('#kaart', { opacity: 0, duration: .25 }, 0);
        scramble(titelEl, hoofd, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&', 0, .85);
      },
      omlijning: function () {
        tl.from('#kaart', { opacity: 0, scale: 1.08, duration: .5, ease: 'power3.out' }, 0)
          .fromTo('#vul', { opacity: 0, clipPath: 'inset(100% 0 0 0)' },
            { opacity: 1, clipPath: 'inset(0% 0 0 0)', duration: .6, ease: 'power2.inOut' }, .35);
      },
      gestapeld: function () {
        delen.forEach(function (r, k) {
          tl.from(r, {
            opacity: 0, x: (k % 2 ? 1 : -1) * em * .7, duration: .5, ease: 'power3.out'
          }, k * .1);
        });
      },
      markeer: function () {
        tl.from('#kaart', { opacity: 0, duration: .3 }, 0)
          .fromTo('#titel', { backgroundSize: '0% 100%' },
            { backgroundSize: '100% 100%', duration: .5, ease: 'power2.inOut' }, .2);
      },
      gewicht: function () {
        var staat = { w: 200 };
        tl.from('#kaart', { opacity: 0, duration: .35 }, 0)
          .to(staat, {
            w: spec.gewicht || 900, duration: .7, ease: 'power2.out',
            onUpdate: function () {
              kaart.style.fontVariationSettings = "'wght' " + Math.round(staat.w);
            }
          }, .1);
      },
      hoofdstuk: function () {
        tl.from('#kaart', { opacity: 0, duration: .7, ease: 'power2.out' }, 0)
          .fromTo('#kaart', { scale: 1 }, { scale: 1.07, duration: duur, ease: 'none' }, 0);
      },
      minimaal: function () {
        tl.from('#kaart', { opacity: 0, y: em * .6, duration: .9, ease: 'power2.out' }, 0);
      }
    };

    (ANIMATIES[spec.id] || ANIMATIES.minimaal)();
    tl.to('#kaart', { opacity: 0, duration: .5, ease: 'power2.in' }, uit);
    if (spec.balk) tl.to('#balk', { opacity: 0, duration: .5, ease: 'power2.in' }, uit);

    window.__timelines = window.__timelines || {};
    if (voorbeeld) {
      // Het voorbeeldbeeld voor de interface: de animatie halverwege, stil.
      // De échte tijdlijn mag de renderer niet terugspoelen naar frame 0 — dan
      // staat er een leeg beeld. Maar er móet er een geregistreerd zijn: zonder
      // dat wacht de renderer 45 seconden op een tijdlijn die nooit komt
      // (`sub_timeline_readiness_timeout`) en duurt één voorbeeldframe 46 s.
      tl.progress(0.5).pause();
      window.__timelines['titel20'] = gsap.timeline({ paused: true });
    } else {
      window.__timelines['titel20'] = tl;
    }
  }

  var families = [spec.font, spec.subfont].filter(Boolean);
  var klaar = families.map(function (f) {
    try {
      return document.fonts.load(
        (spec.cursief || 'normal') + ' ' + (spec.gewicht || 400) + ' 100px ' + f, hoofd);
    } catch (e) { return Promise.resolve(); }
  });
  Promise.all(klaar)
    .then(function () { return document.fonts.ready; })
    .then(afmaken)
    .catch(afmaken);
})();
