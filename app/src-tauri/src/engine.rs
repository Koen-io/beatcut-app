//! De Python-engine als sidecar: JSON-RPC over stdin/stdout, één regel per bericht.
//!
//! Waarom geen poort: geen firewallmelding op Windows, geen botsing met een
//! bezette poort, en de engine sterft vanzelf als de app sluit.
//! Protocol: zie `engine/cve/rpc.py`.
//!
//! **Eén leesdraad, niet één lezer per vraag.** De engine stuurt twee soorten
//! regels: antwoorden (met `id`) en gebeurtenissen (zonder `id`, voor
//! voortgang). Wie zelf zou lezen terwijl hij op zijn antwoord wacht, moet
//! daarvoor de pijp bezet houden — en dan staat een tweede vraag stil zolang
//! een trage vraag loopt, en gaan gebeurtenissen verloren. Daarom leest één
//! draad alles en deelt hij het uit: antwoorden over een kanaal naar de
//! wachtende vrager, gebeurtenissen naar een callback.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// Hoe lang een vraag mag duren voordat we hem opgeven. Ruim: `doctor` draait
/// echte controles. Een vraag die de engine stil laat hangen zou zonder dit
/// een draad voorgoed vastzetten.
const GEDULD: Duration = Duration::from_secs(600);

/// Wat er met een ongevraagd bericht van de engine gebeurt.
/// In de app: `app.emit("engine-gebeurtenis", …)`.
pub type OpGebeurtenis = Arc<dyn Fn(String, Value) + Send + Sync>;

type Wachtenden = Arc<Mutex<HashMap<u64, Sender<Value>>>>;

pub struct Engine {
    child: Mutex<std::process::Child>,
    stdin: Mutex<std::process::ChildStdin>,
    wachtenden: Wachtenden,
    volgende_id: AtomicU64,
}

impl Drop for Engine {
    fn drop(&mut self) {
        if let Ok(mut c) = self.child.lock() {
            let _ = c.kill();
            let _ = c.wait();
        }
        // De leesdraad ziet daarna einde-bestand en stopt zelf.
    }
}

/// Hoe de engine gestart wordt: programma + argumenten + extra omgeving.
/// `omgeving` is er voor `CVE_PROJECTEN` — waar de video's van de gebruiker
/// staan. Leeg laten betekent: de engine kiest zelf (zie `paths.py`).
#[derive(Debug, Clone)]
pub struct Opstart {
    pub programma: PathBuf,
    pub args: Vec<String>,
    pub omgeving: Vec<(String, String)>,
}

impl Opstart {
    pub fn rpc(programma: impl Into<PathBuf>) -> Opstart {
        Opstart {
            programma: programma.into(),
            args: vec!["rpc".to_string()],
            omgeving: Vec::new(),
        }
    }
}

fn venv_cve(wortel: &Path) -> PathBuf {
    if cfg!(windows) {
        wortel.join(".venv").join("Scripts").join("cve.exe")
    } else {
        wortel.join(".venv").join("bin").join("cve")
    }
}

/// Waar de installer de ingevroren engine neerzet (bundle-resource `engine/`).
/// macOS: `BeatCut.app/Contents/Resources/engine/`; Windows: naast de exe.
fn ingebouwde_engine(exe_map: &Path) -> Vec<PathBuf> {
    let naam = if cfg!(windows) { "beatcut-engine.exe" } else { "beatcut-engine" };
    vec![
        exe_map.join("..").join("Resources").join("engine").join(naam),
        exe_map.join("engine").join(naam),
        exe_map.join(naam),
    ]
}

/// Zoekt de engine, in deze volgorde:
/// 1. `BEATCUT_ENGINE` (pad naar een cve-programma) — voor testen
/// 2. in de app zelf: de ingevroren engine uit de installer
/// 3. tijdens ontwikkelen: `.venv` in de projectmap boven `app/`
///    (uit te zetten met `BEATCUT_GEEN_DEV=1`, om stap 2 te kunnen toetsen)
pub fn zoek_engine() -> Result<Opstart, String> {
    if let Some(p) = std::env::var_os("BEATCUT_ENGINE") {
        return Ok(Opstart::rpc(PathBuf::from(p)));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(map) = exe.parent() {
            if let Some(p) = ingebouwde_engine(map).into_iter().find(|p| p.is_file()) {
                return Ok(Opstart::rpc(p));
            }
        }
    }
    if std::env::var_os("BEATCUT_GEEN_DEV").is_some() {
        return Err("Geen ingebouwde engine gevonden in de app (BEATCUT_GEEN_DEV staat aan)".into());
    }
    // CARGO_MANIFEST_DIR = app/src-tauri; de projectwortel ligt twee hoger.
    let wortel = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
    let p = venv_cve(&wortel);
    if p.is_file() {
        return Ok(Opstart::rpc(p));
    }
    Err(format!(
        "Engine niet gevonden. Gezocht: BEATCUT_ENGINE, beatcut-engine naast de app, en {}",
        p.display()
    ))
}

impl Engine {
    pub fn start(o: &Opstart, op_gebeurtenis: OpGebeurtenis) -> Result<Engine, String> {
        use std::process::{Command, Stdio};
        let mut cmd = Command::new(&o.programma);
        cmd.args(&o.args)
            .envs(o.omgeving.iter().map(|(k, v)| (k.as_str(), v.as_str())))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("engine starten mislukt ({}): {e}", o.programma.display()))?;
        let stdin = child.stdin.take().ok_or("geen stdin naar de engine")?;
        let stdout = child.stdout.take().ok_or("geen stdout van de engine")?;

        let wachtenden: Wachtenden = Arc::new(Mutex::new(HashMap::new()));
        lees_draad(BufReader::new(stdout), wachtenden.clone(), op_gebeurtenis);

        Ok(Engine {
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
            wachtenden,
            volgende_id: AtomicU64::new(1),
        })
    }

    /// Eén verzoek, wacht op het antwoord met hetzelfde id.
    /// `&self`, niet `&mut self`: meerdere vragen tegelijk moeten kunnen.
    pub fn vraag(&self, methode: &str, params: Value) -> Result<Value, String> {
        let id = self.volgende_id.fetch_add(1, Ordering::Relaxed);
        let (zender, ontvanger) = channel();
        self.wachtenden
            .lock()
            .map_err(|_| "engine-slot vergiftigd")?
            .insert(id, zender);

        let verzoek = json!({ "id": id, "methode": methode, "params": params });
        // Alleen het schrijven staat onder slot, nooit het wachten.
        let geschreven = {
            let mut pijp = self.stdin.lock().map_err(|_| "engine-slot vergiftigd")?;
            writeln!(pijp, "{verzoek}").and_then(|_| pijp.flush())
        };
        if let Err(e) = geschreven {
            self.vergeet(id);
            // "gestopt" in de tekst: daarop herstart `EngineStaat` één keer.
            return Err(format!("de engine is gestopt bij het schrijven: {e}"));
        }

        match ontvanger.recv_timeout(GEDULD) {
            Ok(antwoord) => {
                if let Some(fout) = antwoord.get("fout") {
                    let bericht =
                        fout.get("bericht").and_then(Value::as_str).unwrap_or("onbekende fout");
                    return Err(bericht.to_string());
                }
                Ok(antwoord.get("resultaat").cloned().unwrap_or(Value::Null))
            }
            // De leesdraad gooide de zender weg: einde-bestand, engine dood.
            Err(RecvTimeoutError::Disconnected) => Err("de engine is gestopt".into()),
            Err(RecvTimeoutError::Timeout) => {
                self.vergeet(id);
                Err(format!("de engine antwoordt niet op '{methode}' ({GEDULD:?})"))
            }
        }
    }

    fn vergeet(&self, id: u64) {
        if let Ok(mut m) = self.wachtenden.lock() {
            m.remove(&id);
        }
    }
}

/// De enige lezer van de pijp. Antwoorden naar de wachtende vrager,
/// gebeurtenissen naar de callback, rommel in de prullenbak.
fn lees_draad(
    mut uit: BufReader<std::process::ChildStdout>,
    wachtenden: Wachtenden,
    op_gebeurtenis: OpGebeurtenis,
) {
    std::thread::spawn(move || {
        let mut regel = String::new();
        loop {
            regel.clear();
            match uit.read_line(&mut regel) {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
            let bericht: Value = match serde_json::from_str(regel.trim()) {
                Ok(v) => v,
                Err(_) => continue, // geen protocolregel: negeren, nooit crashen
            };
            if let Some(id) = bericht.get("id").and_then(Value::as_u64) {
                let zender = wachtenden.lock().ok().and_then(|mut m| m.remove(&id));
                if let Some(z) = zender {
                    let _ = z.send(bericht);
                }
            } else if let Some(naam) = bericht.get("gebeurtenis").and_then(Value::as_str) {
                let data = bericht.get("data").cloned().unwrap_or(Value::Null);
                op_gebeurtenis(naam.to_string(), data);
            }
        }
        // Pijp dicht. Alle zenders weggooien, zodat wie nog wacht meteen
        // "de engine is gestopt" krijgt in plaats van tien minuten stilte.
        if let Ok(mut m) = wachtenden.lock() {
            m.clear();
        }
    });
}

/// Gedeelde engine voor de app. Start lui en herstart één keer als hij weg is.
pub struct EngineStaat {
    huidige: Mutex<Option<Arc<Engine>>>,
    op_gebeurtenis: OpGebeurtenis,
}

impl Default for EngineStaat {
    fn default() -> Self {
        Self::nieuw(Arc::new(|_, _| {}))
    }
}

impl EngineStaat {
    pub fn nieuw(op_gebeurtenis: OpGebeurtenis) -> Self {
        EngineStaat { huidige: Mutex::new(None), op_gebeurtenis }
    }

    /// De draaiende engine, of een nieuwe. Het slot is alleen voor het pakken
    /// van de engine — nooit voor het wachten op zijn antwoord.
    fn engine(&self) -> Result<Arc<Engine>, String> {
        let mut slot = self.huidige.lock().map_err(|_| "engine-slot vergiftigd")?;
        if slot.is_none() {
            *slot = Some(Arc::new(Engine::start(&zoek_engine()?, self.op_gebeurtenis.clone())?));
        }
        Ok(slot.as_ref().expect("net gezet").clone())
    }

    /// Gooi déze engine weg, maar alleen als er niet al een nieuwe staat.
    fn gooi_weg(&self, oud: &Arc<Engine>) {
        if let Ok(mut slot) = self.huidige.lock() {
            if slot.as_ref().is_some_and(|nu| Arc::ptr_eq(nu, oud)) {
                *slot = None;
            }
        }
    }

    pub fn vraag(&self, methode: &str, params: Value) -> Result<Value, String> {
        for poging in 0..2 {
            let eng = self.engine()?;
            match eng.vraag(methode, params.clone()) {
                Ok(v) => return Ok(v),
                Err(e) if poging == 0 && e.contains("gestopt") => self.gooi_weg(&eng),
                Err(e) => return Err(e),
            }
        }
        Err("de engine stopt steeds".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Draait tegen de echte engine uit `.venv` — de snelste toets dat het
    /// contract tussen Rust en Python klopt.
    #[test]
    fn hallo_en_doctor_via_de_echte_engine() {
        let staat = EngineStaat::default();
        let hallo = staat.vraag("hallo", json!({})).expect("hallo");
        assert_eq!(hallo["protocol"], 1);
        let doc = staat.vraag("doctor", json!({})).expect("doctor");
        assert!(doc["checks"].as_array().map(|a| !a.is_empty()).unwrap_or(false));
        let fout = staat.vraag("bestaat-niet", json!({})).unwrap_err();
        assert!(fout.contains("onbekende methode"));
    }

    /// Twee vragen tegelijk over dezelfde engine: niemand mag op de ander
    /// hoeven wachten, en de antwoorden mogen niet verwisseld raken.
    #[test]
    fn twee_vragen_tegelijk_krijgen_hun_eigen_antwoord() {
        let staat = Arc::new(EngineStaat::default());
        let draden: Vec<_> = (0..4)
            .map(|i| {
                let s = staat.clone();
                std::thread::spawn(move || {
                    let m = if i % 2 == 0 { "hallo" } else { "projecten" };
                    (m, s.vraag(m, json!({})))
                })
            })
            .collect();
        for d in draden {
            let (m, uit) = d.join().expect("draad");
            let v = uit.unwrap_or_else(|e| panic!("{m} mislukte: {e}"));
            if m == "hallo" {
                assert_eq!(v["engine"], "beatcut");
            } else {
                assert!(v.is_array(), "projecten moet een lijst zijn, kreeg {v}");
            }
        }
    }

    fn heeft_ffmpeg() -> bool {
        std::process::Command::new("ffmpeg")
            .arg("-version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    /// Twee seconden testbeeld met toon. Klein, maar echt video.
    fn maak_clip(doel: &Path) {
        let uit = std::process::Command::new("ffmpeg")
            .args([
                "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest",
            ])
            .arg(doel)
            .output()
            .expect("ffmpeg starten");
        assert!(uit.status.success(), "{}", String::from_utf8_lossy(&uit.stderr));
    }

    /// De hele motor van stap 1: project maken, twee clips erin, verwerken,
    /// en wachten tot de engine zelf "klaar" roept. Dit is de enige test die
    /// bewijst dat gebeurtenissen écht door de pijp komen en niet alleen in
    /// Python bestaan.
    #[test]
    fn importeren_en_verwerken_met_voortgang_tot_klaar() {
        if !heeft_ffmpeg() {
            eprintln!("ffmpeg niet gevonden — test overgeslagen");
            return;
        }
        let tijdelijk =
            std::env::temp_dir().join(format!("beatcut-rust-test-{}", std::process::id()));
        let bronnen = tijdelijk.join("camera");
        std::fs::create_dir_all(&bronnen).expect("tijdelijke map");
        let paden: Vec<PathBuf> = ["clip-a.mp4", "clip-b.mp4"]
            .iter()
            .map(|n| {
                let p = bronnen.join(n);
                maak_clip(&p);
                p
            })
            .collect();

        // Eigen projectmap voor deze test: niets raakt de echte projecten.
        let mut opstart = zoek_engine().expect("engine gevonden");
        opstart.omgeving.push((
            "CVE_PROJECTEN".to_string(),
            tijdelijk.join("projecten").to_string_lossy().to_string(),
        ));
        let (zender, gebeurtenissen) = channel();
        let zender = Mutex::new(zender);
        let eng = Engine::start(
            &opstart,
            Arc::new(move |naam, data| {
                let _ = zender.lock().expect("zender").send((naam, data));
            }),
        )
        .expect("engine starten");

        let status = eng.vraag("project.maak", json!({"naam": "Rust Proef"})).expect("maak");
        assert_eq!(status["naam"], "rust-proef");

        let toe = eng
            .vraag(
                "project.voegtoe",
                json!({"project": "rust-proef",
                       "paden": paden.iter().map(|p| p.to_string_lossy()).collect::<Vec<_>>()}),
            )
            .expect("voegtoe");
        assert_eq!(toe["status"]["aantal_clips"], 2);

        let gestart = eng
            .vraag("project.verwerk", json!({"project": "rust-proef", "stijl": "landschap"}))
            .expect("verwerk");
        assert_eq!(gestart["gestart"], true);

        // Wachten op "klaar", met 120 s als harde grens voor het geheel.
        let grens = std::time::Instant::now() + Duration::from_secs(120);
        let mut voortgang = 0usize;
        let mut afgerond = None;
        while std::time::Instant::now() < grens {
            let rest = grens - std::time::Instant::now();
            match gebeurtenissen.recv_timeout(rest) {
                Ok((naam, data)) => match naam.as_str() {
                    "voortgang" => {
                        assert_eq!(data["project"], "rust-proef");
                        assert!(data["tekst"].is_string(), "voortgang zonder tekst: {data}");
                        voortgang += 1;
                    }
                    "klaar" | "fout" => {
                        afgerond = Some((naam, data));
                        break;
                    }
                    _ => {}
                },
                Err(_) => break,
            }
        }

        let (naam, data) = afgerond.expect("geen klaar- of fout-gebeurtenis binnen 120 s");
        assert_eq!(naam, "klaar", "engine meldde een fout: {data}");
        assert!(voortgang >= 2, "te weinig voortgangsberichten: {voortgang}");

        let clips = eng.vraag("project.clips", json!({"project": "rust-proef"})).expect("clips");
        let lijst = clips.as_array().expect("lijst");
        assert_eq!(lijst.len(), 2);
        for c in lijst {
            assert_eq!(c["aan"], true);
            assert!(c["id"].as_str().expect("id").starts_with('C'));
            let beeldje = c["thumbnail"].as_str().expect("thumbnail");
            assert!(Path::new(beeldje).is_file(), "beeldje ontbreekt: {beeldje}");
        }

        let uit = eng
            .vraag("clip.zet", json!({"project": "rust-proef", "clip": "clip-a.mp4", "aan": false}))
            .expect("clip.zet");
        assert_eq!(uit["aan"], false);

        drop(eng);
        let _ = std::fs::remove_dir_all(&tijdelijk);
    }

    /// Een gestopte engine mag geen blijvende storing zijn.
    #[test]
    fn na_een_gestopte_engine_komt_er_een_nieuwe() {
        let staat = EngineStaat::default();
        assert!(staat.vraag("hallo", json!({})).is_ok());
        {
            let mut slot = staat.huidige.lock().expect("slot");
            if let Some(eng) = slot.as_ref() {
                let mut kind = eng.child.lock().expect("kind");
                let _ = kind.kill();
                let _ = kind.wait();
            }
            drop(slot.take()); // weg, alsof hij zelf gevallen was
        }
        assert_eq!(staat.vraag("hallo", json!({})).expect("opnieuw")["protocol"], 1);
    }
}
