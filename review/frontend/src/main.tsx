// Entry point: mounts the app and defines the four routes. All state lives
// in each page component (no global store) -- the app is small enough that
// prop-drilling/local state is simpler than adding one.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";
import ApplicationDetail from "./pages/ApplicationDetail.tsx";
import ApplicationsList from "./pages/ApplicationsList.tsx";
import MasterResume from "./pages/MasterResume.tsx";
import NewApplication from "./pages/NewApplication.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<ApplicationsList />} />
          <Route path="new" element={<NewApplication />} />
          <Route path="applications/:id" element={<ApplicationDetail />} />
          <Route path="master-resume" element={<MasterResume />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
