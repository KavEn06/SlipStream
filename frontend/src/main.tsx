import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import {
  AppearanceProvider,
  initializeAppearance,
} from "./hooks/useAppearance";

initializeAppearance();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppearanceProvider>
      <App />
    </AppearanceProvider>
  </StrictMode>,
);
