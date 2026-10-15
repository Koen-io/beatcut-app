# Edities

Eén codebase, meerdere apps. Een editie is **een bouwkeuze**, geen kopie:
dezelfde engine, dezelfde interface, een ander merk.

    edities/<id>/
      editie.json        naam, motto, kleuren — wat de interface laat zien
      editie.css         de thematokens die van de standaard afwijken
      logo.png           het beeldmerk (ontbreekt bij beatcut: dan de balkjes)
      tauri.conf.json    merge-patch op app/src-tauri/tauri.conf.json:
                         productName, identifier, iconen, updater-endpoint
      icons/             door `npm run tauri icon` gemaakt uit bron/
      bron/              het aangeleverde beeldmerk, onaangeraakt

Kiezen doe je met `BEATCUT_EDITIE=<id>` (standaard `beatcut`):

    BEATCUT_EDITIE=p-alv npm run tauri build -- --config edities/p-alv/tauri.conf.json

`BEATCUT_EDITIE` stuurt Vite (de `@editie`-alias wijst naar deze map) en
`--config` stuurt Tauri. Ze horen bij elkaar: alleen Vite zetten geeft een app
die P-ALV heet maar als BeatCut installeert; alleen `--config` geeft het
omgekeerde. `app/edities/bouw.sh` doet beide in één keer.

De engine krijgt de naam via `BEATCUT_APPNAAM` (lib.rs zet hem uit
`productName`) en leidt daar zijn steunmap en Films-map van af — dus twee
edities naast elkaar delen geen projecten en geen modellen.

**Een editie-map met een merk van derden (p-alv) gaat nooit in de publieke
bouwrepo.** `installer/publiek.sh` laat hem weg; de CI haalt hem als
merkpakket uit de privé-releases-repo van die editie.
