import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "ol/ol.css";
import "./styles.css";
import "./platform/platform.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);

const productionBuild = (import.meta as ImportMeta & { env?: { PROD?: boolean } }).env?.PROD;
if ("serviceWorker" in navigator && productionBuild) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}
