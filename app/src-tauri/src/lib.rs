mod engine;

use engine::EngineStaat;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tauri::{Emitter, Manager};

/// Elke ongevraagde regel van de engine wordt één venstergebeurtenis.
/// De interface luistert met `listen("engine-gebeurtenis", …)` en kijkt zelf
/// naar `gebeurtenis`: "voortgang", "klaar" of "fout".
const GEBEURTENIS: &str = "engine-gebeurtenis";

/// Eén ingang voor de interface: elke engine-methode, met params als JSON.
/// De engine kan seconden nodig hebben, dus het wachten gebeurt op een
/// werkdraad, nooit op de UI-draad.
#[tauri::command]
async fn engine(app: tauri::AppHandle, methode: String, params: Option<Value>) -> Result<Value, String> {
    let params = params.unwrap_or_else(|| json!({}));
    tauri::async_runtime::spawn_blocking(move || app.state::<EngineStaat>().vraag(&methode, params))
        .await
        .map_err(|e| format!("engine-draad: {e}"))?
}

/// `BeatCut --zelftest`: start de engine zonder venster, vraag hallo + doctor,
/// print het resultaat en stop. Bewijs dat de gebouwde app zijn engine vindt.
pub fn zelftest() -> i32 {
    let staat = EngineStaat::default();
    match engine::zoek_engine() {
        Ok(o) => println!("engine: {} {}", o.programma.display(), o.args.join(" ")),
        Err(e) => {
            eprintln!("{e}");
            return 2;
        }
    }
    let hallo = match staat.vraag("hallo", json!({})) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("hallo mislukt: {e}");
            return 3;
        }
    };
    println!("hallo: {hallo}");
    match staat.vraag("doctor", json!({})) {
        Ok(d) => {
            let ok = d["ok"].as_bool().unwrap_or(false);
            for c in d["checks"].as_array().cloned().unwrap_or_default() {
                let merk = if c["ok"].as_bool() == Some(true) { "ok" } else { "--" };
                println!("  {merk}  {}  {}", c["naam"].as_str().unwrap_or(""), c["detail"].as_str().unwrap_or(""));
            }
            println!("doctor: {}", if ok { "groen" } else { "rood" });
            if ok { 0 } else { 1 }
        }
        Err(e) => {
            eprintln!("doctor mislukt: {e}");
            4
        }
    }
}

/// Het asset-protocol mag bij de beeldjes van de clipkaarten.
///
/// De vaste plekken (`$VIDEO/BeatCut`, `$HOME/BeatCut`) staan in
/// `tauri.conf.json`. Deze twee kunnen daar niet staan omdat hun pad per
/// machine verschilt: de map die `CVE_PROJECTEN` aanwijst, en bij een
/// ontwikkelbuild de `projecten/` map naast de engine. Zonder dit laat de
/// webview de thumbnails van `npm run tauri dev` gewoon leeg.
fn beeldjes_toestaan(app: &tauri::AppHandle) {
    let scope = app.asset_protocol_scope();
    let mut mappen: Vec<PathBuf> = Vec::new();
    if let Some(eigen) = std::env::var_os("CVE_PROJECTEN") {
        mappen.push(PathBuf::from(eigen));
    }
    if cfg!(debug_assertions) {
        // CARGO_MANIFEST_DIR = app/src-tauri; de projectwortel ligt twee hoger.
        mappen.push(Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("projecten"));
    }
    for m in mappen {
        if let Err(e) = scope.allow_directory(&m, true) {
            eprintln!("asset-scope {} kon niet open: {e}", m.display());
        }
    }
}

/// De updaterplugin. Het endpoint staat in `tauri.conf.json`; de app zelf kan
/// er niets aan veranderen. Alleen `--updatetest` (feature `testendpoint`)
/// bouwt zijn eigen updater met een ander endpoint, en die vlag zit in geen
/// enkele uitgedeelde build.
fn updater() -> tauri::plugin::TauriPlugin<tauri::Wry, tauri_plugin_updater::Config> {
    tauri_plugin_updater::Builder::new().build()
}

/// `BeatCut --updatetest`: kijk één keer bij het endpoint, haal de update op,
/// laat de updater de handtekening controleren, en stop. Er wordt niets
/// geïnstalleerd. Bestaat alleen in een build met `--features testendpoint`;
/// zie installer/LEESMIJ.md § "De updater zelf nakijken".
///
/// Afloopcodes: 0 = update gevonden en handtekening in orde, 1 = niets te
/// doen, 2 = de update is geweigerd (bijvoorbeeld een valse handtekening).
#[cfg(feature = "testendpoint")]
pub fn updatetest() -> i32 {
    use tauri_plugin_updater::UpdaterExt;

    let app = match tauri::Builder::default()
        .plugin(updater())
        .build(tauri::generate_context!())
    {
        Ok(a) => a,
        Err(e) => {
            eprintln!("app kon niet gebouwd worden: {e}");
            return 3;
        }
    };
    tauri::async_runtime::block_on(async move {
        let mut maker = app.updater_builder();
        // http naar 127.0.0.1 mag alleen in een debug-build; de updater weigert
        // het in een release. Dat is precies de grens die we willen.
        if let Ok(url) = std::env::var("BEATCUT_UPDATE_ENDPOINT") {
            eprintln!("TESTBUILD: updater kijkt naar {url}");
            maker = match url.parse().map(|u| maker.endpoints(vec![u])) {
                Ok(Ok(m)) => m,
                _ => {
                    eprintln!("BEATCUT_UPDATE_ENDPOINT is niet bruikbaar: {url}");
                    return 3;
                }
            };
        }
        let bouwer = match maker.build() {
            Ok(u) => u,
            Err(e) => {
                eprintln!("updater niet beschikbaar: {e}");
                return 3;
            }
        };
        match bouwer.check().await {
            Ok(Some(update)) => {
                println!("gevonden: {} -> {}", update.current_version, update.version);
                // download() doet de minisign-controle; een valse handtekening
                // komt hier als fout terug en er wordt niets uitgepakt.
                match update.download(|_, _| {}, || {}).await {
                    Ok(bytes) => {
                        println!("opgehaald: {} bytes, handtekening in orde", bytes.len());
                        0
                    }
                    Err(e) => {
                        eprintln!("GEWEIGERD: {e}");
                        2
                    }
                }
            }
            Ok(None) => {
                println!("geen nieuwere versie");
                1
            }
            Err(e) => {
                eprintln!("controle mislukte: {e}");
                2
            }
        }
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(updater())
        .setup(|app| {
            beeldjes_toestaan(app.handle());
            // De callback heeft de AppHandle nodig, en die bestaat pas hier.
            let handle = app.handle().clone();
            app.manage(EngineStaat::nieuw(Arc::new(move |naam, data| {
                let _ = handle.emit(GEBEURTENIS, json!({"gebeurtenis": naam, "data": data}));
            })));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine])
        .run(tauri::generate_context!())
        .expect("BeatCut kon niet starten");
}
