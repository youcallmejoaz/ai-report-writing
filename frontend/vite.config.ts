import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local development: proxy /api to the FastAPI backend (uvicorn app.main:app --port 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
