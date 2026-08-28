import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";
import ApplicationDetail from "./pages/ApplicationDetail.tsx";
import ApplicationsList from "./pages/ApplicationsList.tsx";
import NewApplication from "./pages/NewApplication.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<ApplicationsList />} />
          <Route path="new" element={<NewApplication />} />
          <Route path="applications/:id" element={<ApplicationDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
