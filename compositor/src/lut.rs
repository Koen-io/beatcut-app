//! `.cube`-bestanden inlezen. 33³ met DOMAIN 0..1 is wat `looks/` bevat.

/// Geeft de tabel als RGBA-viertallen (rood loopt het snelst) en de maat.
///
/// Zonder pad komt er een identiteits-LUT van 2³ terug: dan rekent de shader
/// hetzelfde pad af zonder dat er een tweede codepad voor "geen look" nodig is.
pub fn lees(pad: &str) -> Result<(Vec<f32>, u32), String> {
    if pad.is_empty() || pad == "geen" {
        let mut d = Vec::with_capacity(8 * 4);
        for b in 0..2 {
            for g in 0..2 {
                for r in 0..2 {
                    d.extend_from_slice(&[r as f32, g as f32, b as f32, 1.0]);
                }
            }
        }
        return Ok((d, 2));
    }
    let tekst = std::fs::read_to_string(pad).map_err(|e| format!("LUT {pad}: {e}"))?;
    let mut maat = 0u32;
    let mut data: Vec<f32> = Vec::new();
    for regel in tekst.lines() {
        let regel = regel.trim();
        if regel.is_empty() || regel.starts_with('#') {
            continue;
        }
        if let Some(rest) = regel.strip_prefix("LUT_3D_SIZE") {
            maat = rest.trim().parse().map_err(|_| "LUT_3D_SIZE onleesbaar")?;
            continue;
        }
        let eerste = regel.as_bytes()[0];
        if !(eerste.is_ascii_digit() || eerste == b'-' || eerste == b'.') {
            continue; // TITLE, DOMAIN_MIN, DOMAIN_MAX
        }
        let getallen: Vec<f32> = regel.split_whitespace().filter_map(|x| x.parse().ok()).collect();
        if getallen.len() == 3 {
            data.extend_from_slice(&[getallen[0], getallen[1], getallen[2], 1.0]);
        }
    }
    if maat == 0 {
        return Err(format!("LUT {pad}: geen LUT_3D_SIZE"));
    }
    let verwacht = (maat as usize).pow(3);
    if data.len() / 4 != verwacht {
        return Err(format!(
            "LUT {pad}: {} regels, verwacht {verwacht}",
            data.len() / 4
        ));
    }
    Ok((data, maat))
}

#[cfg(test)]
mod tests {
    #[test]
    fn identiteit_zonder_pad() {
        let (d, n) = super::lees("").unwrap();
        assert_eq!(n, 2);
        assert_eq!(d.len(), 8 * 4);
        assert_eq!(&d[0..3], &[0.0, 0.0, 0.0]);
        assert_eq!(&d[28..31], &[1.0, 1.0, 1.0]);
    }
}
