import React from "react";
import ReactDOM from "react-dom/client";
// Lettertypes zitten in de app zelf (OFL), nooit via internet: bij Spam Buster
// brak een externe font offline op Windows.
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("app") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
