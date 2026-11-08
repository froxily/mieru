import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { MetricDebuggerProvider } from "./components/MetricDebugger";
import { initializeTheme } from "./lib/theme";
import "./styles/global.css";
import { MieruSplash } from "./intro/MieruIntro";

initializeTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found");

createRoot(root).render(
  <StrictMode>
    <MieruSplash />
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <MetricDebuggerProvider>
          <App />
        </MetricDebuggerProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
