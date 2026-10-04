//! BeatCut-compositor: look en afwerking op rauwe RGBA-frames, zonder venster.
//!
//! Hij staat tussen twee ffmpeg's in: de ene decodeert, deze rekent, de andere
//! encodeert.
//!
//! ```text
//! ffmpeg -i bron.mp4 -f rawvideo -pix_fmt rgba - \
//!   | beatcut-compositor --breedte 1920 --hoogte 1080 --aantal 0 \
//!       --lut looks/blockbuster.cube --sterkte 0.85 \
//!       --afwerking '{"korrel":0.3,"vignet":0.2}' --seed 7 \
//!   | ffmpeg -f rawvideo -pix_fmt rgba -s 1920x1080 -i - uit.mp4
//! ```
//!
//! De wiskunde staat niet hier maar in `app/shaders/*.wgsl`. Dat is met opzet:
//! de live voorvertoning in de webview leest dezelfde twee bestanden in, en
//! een tweede implementatie zou vroeg of laat afwijken (PLAN-v2 §4.4).

use std::io::{Read, Write};

/// Zoveel bytes van een klagende ffmpeg bewaren we voor de foutmelding. De
/// rest wordt wel gelezen (anders loopt zijn pijp vol) maar weggegooid.
const BEWAAR: usize = 4096;

/// Een gedeelde, begrensde bak voor meldingen van een kindproces.
type Bak = std::sync::Arc<std::sync::Mutex<Vec<u8>>>;

mod gpu;
mod lut;
mod overgang;
/// De kadering van de speler, headless nagemeten — alleen onder `cargo test`.
#[cfg(test)]
mod spelerproef;

/// Alles wat de keten nodig heeft, in de indeling van `struct Params` in beide
/// shaders. 20 × 4 bytes = 80, een veelvoud van 16.
#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable, Default)]
pub struct Params {
    pub breedte: u32,
    pub hoogte: u32,
    pub frame: u32,
    pub seed: u32,
    pub sterkte: f32,
    pub lut_grootte: u32,
    pub korrel: f32,
    pub vignet: f32,
    pub halation: f32,
    pub gloed: f32,
    pub lichtlek: f32,
    pub breedbeeld: f32,
    pub filmtrilling: f32,
    pub kleurrand: f32,
    pub drempel: f32,
    pub dekking: f32,
    pub mix_r: f32,
    pub mix_g: f32,
    pub mix_b: f32,
    pub straal: u32,
}

/// De afwerking zoals `edl.Afwerking` hem kent, allemaal 0..1.
#[derive(Clone, Copy, Default)]
pub struct Afwerking {
    pub korrel: f32,
    pub halation: f32,
    pub gloed: f32,
    pub vignet: f32,
    pub lichtlek: f32,
    pub breedbeeld: f32,
    pub filmtrilling: f32,
    pub kleurrand: f32,
}

impl Afwerking {
    fn uit_json(tekst: &str) -> Result<Self, String> {
        if tekst.trim().is_empty() {
            return Ok(Self::default());
        }
        let v: serde_json::Value =
            serde_json::from_str(tekst).map_err(|e| format!("afwerking-JSON: {e}"))?;
        let pak = |naam: &str| -> f32 {
            v.get(naam).and_then(|x| x.as_f64()).unwrap_or(0.0).clamp(0.0, 1.0) as f32
        };
        Ok(Self {
            korrel: pak("korrel"),
            halation: pak("halation"),
            gloed: pak("gloed"),
            vignet: pak("vignet"),
            lichtlek: pak("lichtlek"),
            breedbeeld: pak("breedbeeld"),
            filmtrilling: pak("filmtrilling"),
            kleurrand: pak("kleurrand"),
        })
    }
}

/// Een gaussische kernel met een expliciete straal, genormaliseerd op 1.
///
/// Geen IIR-benadering zoals ffmpeg `gblur`: expliciete gewichten zijn in de
/// shader en in de numpy-referentie exact dezelfde getallen, en dat is wat de
/// gouden-frames-poort meet. `tests/ref_compositor.py` rekent het identiek uit.
pub fn kernel(sigma: f32) -> Vec<f32> {
    let straal = ((3.0 * sigma).ceil() as i32).clamp(1, 64);
    let mut w: Vec<f32> = (-straal..=straal)
        .map(|k| (-(k * k) as f32 / (2.0 * sigma * sigma)).exp())
        .collect();
    let som: f32 = w.iter().sum();
    for x in w.iter_mut() {
        *x /= som;
    }
    w
}

/// De overgangenlijst als JSON: bij voorkeur uit een bestand.
///
/// Windows kapt een commandoregel af op 32.767 tekens. Vijf minuten montage
/// met shots van een halve seconde geeft 600 overgangen, en alleen die JSON is
/// al ruim 34.000 tekens — dan start dit programma helemaal niet. Vandaar
/// `--overgangen-bestand`. `--overgangen` blijft bestaan voor losse proeven
/// met de hand (`ontwerp/beatcut2/qa/brug.py`).
fn overgangtekst(args: &[String]) -> Result<String, String> {
    let pad = arg(args, "--overgangen-bestand", "");
    if pad.is_empty() {
        return Ok(arg(args, "--overgangen", ""));
    }
    std::fs::read_to_string(&pad).map_err(|e| format!("--overgangen-bestand {pad}: {e}"))
}

fn arg(args: &[String], naam: &str, standaard: &str) -> String {
    args.iter()
        .position(|a| a == naam)
        .and_then(|i| args.get(i + 1))
        .cloned()
        .unwrap_or_else(|| standaard.to_string())
}

/// Lees een pijp op een eigen draad leeg en houd het begin vast.
///
/// Het leeglezen is het punt: een pijp die niemand leest loopt vol en zet de
/// schrijver stil. Het bewaarde begin is er alleen om in de foutmelding te
/// kunnen zetten wát ffmpeg dan te klagen had.
fn meelezen(mut pijp: std::process::ChildStderr) -> Bak {
    let bak: Bak = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let mijn = bak.clone();
    std::thread::spawn(move || {
        let mut brok = [0u8; 4096];
        while let Ok(k) = pijp.read(&mut brok) {
            if k == 0 {
                break;
            }
            let mut b = mijn.lock().unwrap();
            let ruimte = BEWAAR.saturating_sub(b.len());
            if ruimte > 0 {
                b.extend_from_slice(&brok[..k.min(ruimte)]);
            }
        }
    });
    bak
}

fn main() {
    if let Err(fout) = draai() {
        eprintln!("compositor: {fout}");
        std::process::exit(1);
    }
}

fn draai() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();

    // `--info` draait geen frames: het zegt alleen wie er rekent. `cve doctor`
    // en `looks.voorbeeld()` leunen erop — die laatste zet het in de
    // cachesleutel, zodat een andere build nooit een oud voorbeeld hergebruikt.
    if args.iter().any(|a| a == "--info") {
        let (naam, backend) = gpu::info()?;
        println!(
            "{}",
            serde_json::json!({
                "versie": env!("CARGO_PKG_VERSION"),
                "adapter": naam,
                "backend": backend,
            })
        );
        return Ok(());
    }

    let breedte: u32 = arg(&args, "--breedte", "0").parse().map_err(|_| "--breedte")?;
    let hoogte: u32 = arg(&args, "--hoogte", "0").parse().map_err(|_| "--hoogte")?;
    if breedte == 0 || hoogte == 0 {
        return Err("--breedte en --hoogte zijn verplicht".into());
    }
    // 0 = lezen tot stdin leeg is.
    let aantal: u64 = arg(&args, "--aantal", "0").parse().unwrap_or(0);
    let lutpad = arg(&args, "--lut", "");
    let sterkte: f32 = arg(&args, "--sterkte", "1").parse().unwrap_or(1.0);
    let afwerking = Afwerking::uit_json(&arg(&args, "--afwerking", ""))?;
    let seed: u32 = arg(&args, "--seed", "0").parse().unwrap_or(0);
    // Waar de frameteller begint. Korrel en filmtrilling rekenen met het
    // framenummer, dus een los voorbeeldframe van shot 12 moet op diezelfde
    // stand beginnen als de export daar staat — anders ziet de gebruiker in
    // stap Look andere korrel dan hij krijgt.
    let vanaf: u32 = arg(&args, "--vanaf", "0").parse().unwrap_or(0);

    let (lutdata, lutmaat) = lut::lees(&lutpad)?;
    let mut motor = gpu::Motor::nieuw(breedte, hoogte, &lutdata, lutmaat)?;

    let pixels = (breedte as usize) * (hoogte as usize) * 4;
    let mut invoer = vec![0u8; pixels];
    let mut stdin = std::io::stdin().lock();
    let mut stdout = std::io::stdout().lock();

    // Overgangen: aan het begin van blok B loopt blok A nog even door, net als
    // in de speler. De staarten van A staan achter elkaar in één bestand
    // (`--staart`), in dezelfde volgorde als `--overgangen`.
    let overgangen = Overgang::lijst(&overgangtekst(&args)?)?;
    let mut staart = if overgangen.is_empty() {
        None
    } else {
        let ff = arg(&args, "--ffmpeg", "ffmpeg");
        let pad = arg(&args, "--staart", "");
        if pad.is_empty() {
            return Err("--overgangen zonder --staart".into());
        }
        let mut kind = std::process::Command::new(ff)
            // -nostdin én stdin dicht: anders leest ffmpeg toetsaanslagen van
            // ónze stdin — de RGBA-stroom — en schuiven alle frames een paar
            // bytes op (paars en groen beeld, gezien 03-10-2026).
            .args(["-nostdin", "-v", "error", "-i", &pad, "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            // Een eigen stderr-pijp, en meteen leeggelezen op een eigen draad.
            // Zonder dit erft deze ffmpeg de stderr van de compositor, en die
            // staat bij `pas_toe()` op een pijp die Python pas leest als alles
            // klaar is. Beschadigde pakketten vullen die 64 kB, ffmpeg wacht op
            // ruimte, wij wachten op zijn volgende frame, Python wacht op de
            // encoder — en niemand komt er meer uit.
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("ffmpeg voor de staarten: {e}"))?;
        let uit = kind.stdout.take().ok_or("geen stdout van ffmpeg")?;
        let klacht = meelezen(kind.stderr.take().ok_or("geen stderr van ffmpeg")?);
        Some((
            kind,
            std::io::BufReader::with_capacity(pixels, uit),
            overgang::Menger::nieuw(breedte, hoogte)?,
            klacht,
        ))
    };
    let fps: f32 = arg(&args, "--fps", "30").parse().unwrap_or(30.0);
    let mut staartframe = vec![0u8; pixels];

    let mut frame: u64 = 0;
    loop {
        if aantal > 0 && frame >= aantal {
            break;
        }
        match stdin.read_exact(&mut invoer) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
            Err(e) => return Err(format!("stdin: {e}")),
        }
        let globaal = vanaf.wrapping_add(frame as u32);
        let actief = overgangen.iter().find(|o| frame >= o.start && frame < o.start + o.n);
        let gemengd;
        let beeld: &[u8] = match (actief, staart.as_mut()) {
            (Some(o), Some((_, lezer, menger, klacht))) => {
                lezer.read_exact(&mut staartframe).map_err(|e| {
                    let ff = String::from_utf8_lossy(&klacht.lock().unwrap()).trim().to_string();
                    let erbij = if ff.is_empty() { String::new() } else { format!(" | ffmpeg: {ff}") };
                    format!("staart van de overgang op frame {}: {e}{erbij}", o.start)
                })?;
                let m = overgang::Moment {
                    soort: o.soort,
                    meng: (frame - o.start) as f32 / o.duur.max(1e-3),
                    frame: globaal,
                    tijd: globaal as f32 / fps,
                    seed,
                    verhouding: breedte as f32 / hoogte as f32,
                };
                gemengd = menger.meng(&staartframe, &invoer, m)?;
                &gemengd
            }
            _ => &invoer,
        };
        // Pijplijn: het vorige frame terughalen terwijl dit al rekent.
        if motor.onderweg() >= 2 {
            if let Some(uit) = motor.haal()? {
                stdout.write_all(&uit).map_err(|e| format!("stdout: {e}"))?;
            }
        }
        motor.stuur(beeld, globaal, seed, sterkte, &afwerking)?;
        frame += 1;
    }
    while let Some(uit) = motor.haal()? {
        stdout.write_all(&uit).map_err(|e| format!("stdout: {e}"))?;
    }
    stdout.flush().map_err(|e| format!("stdout: {e}"))?;
    if let Some((mut kind, _, _, _)) = staart {
        let _ = kind.kill();
        let _ = kind.wait();
    }
    Ok(())
}

/// Eén overgang op de tijdlijn, in frames van de invoerstroom.
#[derive(Clone, Copy, Debug, PartialEq)]
struct Overgang {
    /// Eerste frame van blok B.
    start: u64,
    /// Aantal frames waarin gemengd wordt (= frames in de staart).
    n: u64,
    /// Duur in frames, niet afgerond: de mengfactor is (f - start) / duur,
    /// net als `(t - start) / overgang_duur` in de speler.
    duur: f32,
    /// Index in `edl.OVERGANGEN`.
    soort: u32,
}

impl Overgang {
    fn lijst(tekst: &str) -> Result<Vec<Self>, String> {
        if tekst.trim().is_empty() {
            return Ok(Vec::new());
        }
        let v: serde_json::Value =
            serde_json::from_str(tekst).map_err(|e| format!("overgangen-JSON: {e}"))?;
        let rij = v.as_array().ok_or("--overgangen moet een lijst zijn")?;
        let mut uit = Vec::new();
        for o in rij {
            let getal = |k: &str| o.get(k).and_then(|x| x.as_f64()).ok_or(format!("overgang mist '{k}'"));
            uit.push(Self {
                start: getal("start")? as u64,
                n: getal("n")? as u64,
                duur: getal("duur")? as f32,
                soort: getal("soort")? as u32,
            });
        }
        uit.sort_by_key(|o| o.start);
        Ok(uit)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kernel_telt_op_tot_een() {
        for sigma in [0.5f32, 1.0, 4.0, 30.0] {
            let w = kernel(sigma);
            let som: f32 = w.iter().sum();
            assert!((som - 1.0).abs() < 1e-5, "sigma {sigma}: som {som}");
            assert_eq!(w.len() % 2, 1, "kernel moet een midden hebben");
        }
    }

    #[test]
    fn kernel_straal_is_begrensd() {
        // Zonder bovengrens zou sigma op 4K een kernel van honderden taps geven.
        assert_eq!(kernel(1000.0).len(), 129);
    }

    #[test]
    fn overgangen_lezen_en_sorteren() {
        let l = Overgang::lijst(r#"[{"start":90,"n":3,"duur":2.4,"soort":7},{"start":30,"n":8,"duur":8,"soort":1}]"#).unwrap();
        assert_eq!(l[0].start, 30);
        assert_eq!(l[1].soort, 7);
        assert!(Overgang::lijst(r#"[{"start":1}]"#).is_err());
        assert!(Overgang::lijst("").unwrap().is_empty());
    }

    #[test]
    fn overgangen_uit_een_bestand() {
        // 600 overgangen passen niet op een Windows-commandoregel (32.767
        // tekens); via een bestand wel.
        let lijst: Vec<String> = (0..600)
            .map(|i| format!(r#"{{"start":{},"n":12,"duur":12,"soort":1}}"#, i * 15))
            .collect();
        let json = format!("[{}]", lijst.join(","));

        let pad = std::env::temp_dir().join("beatcut-overgangen-test.json");
        std::fs::write(&pad, &json).unwrap();
        let args = vec![
            "beatcut-compositor".to_string(),
            "--overgangen-bestand".to_string(),
            pad.to_string_lossy().into_owned(),
        ];
        let gelezen = Overgang::lijst(&overgangtekst(&args).unwrap()).unwrap();
        assert_eq!(gelezen.len(), 600);
        assert_eq!(gelezen[599].start, 599 * 15);
        std::fs::remove_file(&pad).unwrap();

        // Ontbreekt het bestand, dan is dat een fout en geen stille lege lijst.
        let weg = vec![
            "beatcut-compositor".to_string(),
            "--overgangen-bestand".to_string(),
            "/bestaat/niet.json".to_string(),
        ];
        assert!(overgangtekst(&weg).is_err());
        // Zonder vlag blijft de oude weg werken.
        assert_eq!(overgangtekst(&["x".to_string()]).unwrap(), "");
    }

    #[test]
    fn afwerking_klemt_en_negeert_onzin() {
        let a = Afwerking::uit_json(r#"{"korrel":2.0,"onzin":1,"vignet":-1}"#).unwrap();
        assert_eq!(a.korrel, 1.0);
        assert_eq!(a.vignet, 0.0);
        assert!(Afwerking::uit_json("niet-json").is_err());
    }
}
