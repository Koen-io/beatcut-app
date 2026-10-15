//! Zelf bijwerken, voor beide edities met dezelfde drie stappen:
//! controleren, ophalen, installeren. De interface roept ze los aan, zodat
//! de pop-up kan laten zien wat er gebeurt en een installatie nooit begint
//! terwijl de engine nog werk heeft (zie `zelf-bijwerken.ts`).
//!
//! **Twee soorten endpoints, één code.** Het endpoint staat in de Tauri-config
//! van de editie (`plugins.updater.endpoints`):
//!
//! - *Publiek* (BeatCut): een rechtstreekse URL naar `latest.json` op GitHub
//!   Releases. De updaterplugin haalt hem op zoals altijd.
//! - *Privé* (P-ALV): de GitHub-API-URL van de nieuwste release,
//!   `https://api.github.com/repos/<eigenaar>/<repo>/releases/latest`. Een
//!   privé-repo heeft geen vaste downloadlink, dus we vragen eerst aan de API
//!   welke bestanden erbij horen, zoeken `latest.json` en geven de plugin
//!   dát adres — met het token in de kop. De URL's in die `latest.json` zijn
//!   ook API-adressen (`release.sh` schrijft ze zo), en de plugin stuurt
//!   dezelfde koppen mee bij het ophalen van de bundel.
//!
//! Het token komt bij het bouwen uit `BEATCUT_UPDATE_TOKEN` (CI-secret) en
//! zit daarna in het programma; bij een ontwikkelbuild mag het ook uit de
//! omgeving komen. Het is een fijnmazig token dat alleen *lezen* mag op die
//! ene releases-repo — meer kan een uitgelezen token dus ook niet.
//!
//! De handtekening onder elke bundel wordt door de plugin zelf gecontroleerd
//! met `pubkey` uit de config; een token verandert daar niets aan.

use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

/// Gebeurtenis tijdens het ophalen: `{ ontvangen, totaal }` in bytes.
pub const VOORTGANG: &str = "bijwerken-voortgang";

/// Het token dat bij het bouwen is meegegeven. `option_env!` leest het tijdens
/// het compileren; ontbreekt het, dan staat hier `None` en werkt alleen een
/// publiek endpoint.
const INGEBAKKEN_TOKEN: Option<&str> = option_env!("BEATCUT_UPDATE_TOKEN");

#[derive(Default)]
pub struct BijwerkStaat {
    /// De gevonden update, zolang hij nog niet geïnstalleerd is.
    gevonden: Mutex<Option<Update>>,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Controle {
    pub huidige: String,
    pub beschikbaar: bool,
    pub versie: Option<String>,
    pub notities: Option<String>,
    pub datum: Option<String>,
    /// "publiek" of "prive" — alleen ter informatie in het instellingenpaneel.
    pub soort: &'static str,
}

/// Hoe het endpoint uit de config gelezen moet worden.
#[derive(Debug, PartialEq)]
pub enum Endpoint {
    Publiek(String),
    /// `(eigenaar/repo)` van een privé GitHub-repo.
    PriveGithub(String),
}

/// Leest het eerste updater-endpoint uit de Tauri-config en bepaalt het soort.
pub fn lees_endpoint(url: &str) -> Endpoint {
    const API: &str = "https://api.github.com/repos/";
    const STAART: &str = "/releases/latest";
    if let Some(rest) = url.strip_prefix(API) {
        if let Some(repo) = rest.strip_suffix(STAART) {
            if repo.split('/').count() == 2 {
                return Endpoint::PriveGithub(repo.to_string());
            }
        }
    }
    Endpoint::Publiek(url.to_string())
}

fn endpoint_uit_config(app: &AppHandle) -> Result<Endpoint, String> {
    let plugins = &app.config().plugins;
    let url = plugins
        .0
        .get("updater")
        .and_then(|u| u.get("endpoints"))
        .and_then(|e| e.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
        .ok_or("geen updater-endpoint in de config")?;
    Ok(lees_endpoint(url))
}

fn token() -> Option<String> {
    std::env::var("BEATCUT_UPDATE_TOKEN")
        .ok()
        .filter(|t| !t.trim().is_empty())
        .or_else(|| INGEBAKKEN_TOKEN.map(str::to_string))
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent(format!("{}/{}", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|e| format!("http-client: {e}"))
}

/// Wat de GitHub-API over de nieuwste release vertelt, voor zover we het nodig hebben.
#[derive(serde::Deserialize)]
struct ApiRelease {
    tag_name: String,
    draft: bool,
    prerelease: bool,
    body: Option<String>,
    published_at: Option<String>,
    assets: Vec<ApiAsset>,
}

/// Is dit een uitgegeven versie (`v1.2.3`), en geen concept, geen
/// pre-release en geen hulprelease zoals `merk` (het merkpakket)?
pub fn is_versie_release(tag: &str, draft: bool, prerelease: bool) -> bool {
    !draft && !prerelease && tag.strip_prefix('v').is_some_and(|r| r.chars().next().is_some_and(|c| c.is_ascii_digit()))
}

#[derive(serde::Deserialize)]
struct ApiAsset {
    name: String,
    url: String,
}

/// Zoekt bij een privé-repo het API-adres van `latest.json` en de releasetekst.
///
/// Niet `releases/latest`: GitHub wijst daarmee ook de hulprelease `merk`
/// aan (het merkpakket, zonder latest.json) zolang er nog geen versie is,
/// en dan zag de gebruiker bij elke start een foutmelding (15-10-2026). We
/// lezen de laatste releases en nemen de nieuwste échte versie. Is die er
/// niet, dan is er gewoon niets nieuws: `Ok(None)`.
async fn prive_manifest(repo: &str, token: &str) -> Result<Option<(String, Option<String>, Option<String>)>, String> {
    let adres = format!("https://api.github.com/repos/{repo}/releases?per_page=20");
    let antwoord = client()?
        .get(&adres)
        .bearer_auth(token)
        .header("Accept", "application/vnd.github+json")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .send()
        .await
        .map_err(|e| format!("GitHub niet bereikbaar: {e}"))?;
    let status = antwoord.status();
    if status.as_u16() == 404 {
        // Geen release, of het token mag deze repo niet zien — GitHub maakt
        // daar bewust geen onderscheid in.
        return Err("geen release gevonden (of het token mag de repo niet lezen)".into());
    }
    if !status.is_success() {
        return Err(format!("GitHub antwoordde {status}"));
    }
    let releases: Vec<ApiRelease> = antwoord.json().await.map_err(|e| format!("releasegegevens onleesbaar: {e}"))?;
    // GitHub sorteert op aanmaakdatum, nieuwste eerst.
    let Some(release) = releases
        .into_iter()
        .find(|r| is_versie_release(&r.tag_name, r.draft, r.prerelease))
    else {
        return Ok(None);
    };
    let manifest = release
        .assets
        .iter()
        .find(|a| a.name == "latest.json")
        .ok_or_else(|| format!("release {} heeft geen latest.json", release.tag_name))?;
    Ok(Some((manifest.url.clone(), release.body, release.published_at)))
}

/// Bouwt de updater voor dit endpoint, met de juiste koppen. `None`: er is
/// (nog) geen versie om naar te kijken — dat is geen fout.
async fn updater(app: &AppHandle) -> Result<Option<(tauri_plugin_updater::Updater, Option<String>, Option<String>)>, String> {
    let maker = app.updater_builder();
    match endpoint_uit_config(app)? {
        Endpoint::Publiek(_) => {
            // Het endpoint staat al in de config; de plugin leest het zelf.
            Ok(Some((maker.build().map_err(|e| e.to_string())?, None, None)))
        }
        Endpoint::PriveGithub(repo) => {
            let token = token().ok_or(
                "deze build heeft geen updatetoken; bijwerken kan alleen met een installer",
            )?;
            let Some((url, notities, datum)) = prive_manifest(&repo, &token).await? else {
                return Ok(None);
            };
            let url: reqwest::Url = url.parse().map_err(|e| format!("manifest-adres: {e}"))?;
            let maker = maker
                .endpoints(vec![url])
                .map_err(|e| e.to_string())?
                .header("Authorization", format!("Bearer {token}"))
                .map_err(|e| e.to_string())?
                // Zonder dit geeft de API de *beschrijving* van het bestand
                // (JSON) in plaats van het bestand zelf.
                .header("Accept", "application/octet-stream")
                .map_err(|e| e.to_string())?
                .header("X-GitHub-Api-Version", "2022-11-28")
                .map_err(|e| e.to_string())?;
            Ok(Some((maker.build().map_err(|e| e.to_string())?, notities, datum)))
        }
    }
}

fn soort(app: &AppHandle) -> &'static str {
    match endpoint_uit_config(app) {
        Ok(Endpoint::PriveGithub(_)) => "prive",
        _ => "publiek",
    }
}

/// Stap 1: is er een nieuwere versie? Bewaart hem voor stap 2.
#[tauri::command]
pub async fn bijwerken_controleer(app: AppHandle) -> Result<Controle, String> {
    let huidige = app.package_info().version.to_string();
    let (gevonden, notities_api, datum_api) = match updater(&app).await? {
        Some((updater, n, d)) => (updater.check().await.map_err(|e| format!("controle mislukt: {e}"))?, n, d),
        None => (None, None, None),
    };
    let staat = app.state::<BijwerkStaat>();
    let uit = match &gevonden {
        Some(u) => Controle {
            huidige: huidige.clone(),
            beschikbaar: true,
            versie: Some(u.version.clone()),
            // Liever de releasetekst van GitHub (die schrijft Koen zelf) dan
            // de regel uit latest.json; is die er niet, dan de laatste.
            notities: notities_api.or_else(|| u.body.clone()),
            datum: datum_api.or_else(|| u.date.map(|d| d.to_string())),
            soort: soort(&app),
        },
        None => Controle {
            huidige,
            beschikbaar: false,
            versie: None,
            notities: None,
            datum: None,
            soort: soort(&app),
        },
    };
    *staat.gevonden.lock().map_err(|_| "staat vergrendeld")? = gevonden;
    Ok(uit)
}

/// Stap 2: de bundel ophalen en de handtekening laten controleren. Meldt de
/// voortgang als `bijwerken-voortgang`. Installeert niets.
#[tauri::command]
pub async fn bijwerken_ophalen(app: AppHandle) -> Result<u64, String> {
    let update = {
        let staat = app.state::<BijwerkStaat>();
        let g = staat.gevonden.lock().map_err(|_| "staat vergrendeld")?;
        g.clone().ok_or("eerst controleren")?
    };
    let handle = app.clone();
    let mut ontvangen: u64 = 0;
    let bytes = update
        .download(
            |stuk, totaal| {
                ontvangen += stuk as u64;
                let _ = handle.emit(VOORTGANG, serde_json::json!({ "ontvangen": ontvangen, "totaal": totaal }));
            },
            || {},
        )
        .await
        .map_err(|e| format!("ophalen mislukt: {e}"))?;
    let staat = app.state::<BijwerkStaat>();
    *staat.gevonden.lock().map_err(|_| "staat vergrendeld")? = Some(update);
    // De bytes blijven in de staat tot de installatie; een tweede ophalen
    // begint gewoon opnieuw.
    let n = bytes.len() as u64;
    let opgehaald = app.state::<Opgehaald>();
    *opgehaald.0.lock().map_err(|_| "staat vergrendeld")? = Some(bytes);
    Ok(n)
}

/// De opgehaalde bundel, gescheiden van de `Update` zodat `bijwerken_controleer`
/// hem niet per ongeluk weggooit.
#[derive(Default)]
pub struct Opgehaald(Mutex<Option<Vec<u8>>>);

/// Stap 3: installeren. Op Windows sluit de updater de app hierbij zelf af;
/// op macOS en Linux komt de aanroeper terug en herstart die zelf.
#[tauri::command]
pub async fn bijwerken_installeer(app: AppHandle) -> Result<(), String> {
    let update = {
        let staat = app.state::<BijwerkStaat>();
        let g = staat.gevonden.lock().map_err(|_| "staat vergrendeld")?;
        g.clone().ok_or("er is geen update klaargezet")?
    };
    let bytes = {
        let staat = app.state::<Opgehaald>();
        let mut b = staat.0.lock().map_err(|_| "staat vergrendeld")?;
        b.take().ok_or("de update is nog niet opgehaald")?
    };
    tauri::async_runtime::spawn_blocking(move || update.install(bytes))
        .await
        .map_err(|e| format!("installatiedraad: {e}"))?
        .map_err(|e| format!("installeren mislukt: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alleen_een_uitgegeven_v_tag_telt_als_versie() {
        assert!(is_versie_release("v0.4.0", false, false));
        assert!(!is_versie_release("merk", false, false));
        assert!(!is_versie_release("v0.4.0", true, false));
        assert!(!is_versie_release("v0.4.0", false, true));
        assert!(!is_versie_release("versie", false, false));
    }

    #[test]
    fn een_gewone_url_is_publiek() {
        assert_eq!(
            lees_endpoint("https://github.com/Koen-io/beatcut-releases/releases/latest/download/latest.json"),
            Endpoint::Publiek("https://github.com/Koen-io/beatcut-releases/releases/latest/download/latest.json".into())
        );
    }

    #[test]
    fn de_api_url_van_een_release_is_prive() {
        assert_eq!(
            lees_endpoint("https://api.github.com/repos/Koen-io/P-ALV-Movie-Maker-Releases/releases/latest"),
            Endpoint::PriveGithub("Koen-io/P-ALV-Movie-Maker-Releases".into())
        );
    }

    #[test]
    fn een_api_url_zonder_releases_latest_blijft_publiek() {
        // Niet raden: alleen het precieze patroon krijgt het token.
        assert!(matches!(
            lees_endpoint("https://api.github.com/repos/Koen-io/x/releases/tags/v1"),
            Endpoint::Publiek(_)
        ));
        assert!(matches!(
            lees_endpoint("https://api.github.com/repos/Koen-io/releases/latest"),
            Endpoint::Publiek(_)
        ));
    }
}
