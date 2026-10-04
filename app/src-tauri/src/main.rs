// Voorkomt een extra consolevenster op Windows in release. NIET WEGHALEN.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if std::env::args().any(|a| a == "--zelftest") {
        std::process::exit(beatcut_lib::zelftest());
    }
    #[cfg(feature = "testendpoint")]
    if std::env::args().any(|a| a == "--updatetest") {
        std::process::exit(beatcut_lib::updatetest());
    }
    beatcut_lib::run()
}
