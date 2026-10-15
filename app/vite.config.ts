import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { titelBinnenLaag } from "./titelbereik";
// @ts-expect-error type error without @types/node package
import process from "node:process";
// @ts-expect-error type error without @types/node package
import path from "node:path";
const host = process.env.TAURI_DEV_HOST;

// Welke editie er gebouwd wordt (app/edities/LEESMIJ.md). `@editie` wijst
// naar die map; alleen wat de interface daaruit importeert komt in de bundel,
// en de andere edities blijven er helemaal buiten.
const editie = process.env.BEATCUT_EDITIE || "beatcut";
const editieMap = path.resolve(process.cwd(), "edities", editie);

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react(), titelBinnenLaag()],

  resolve: { alias: { "@editie": editieMap } },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
    // De titelcompositie (`brands/sjablonen/titel20.*`) en de lettertypes
    // staan buiten `app/`; zonder dit weigert de dev-server ze te serveren.
    fs: { allow: [".."] },
  },
}));
