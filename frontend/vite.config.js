import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev server runs on :5173 and proxies the API surfaces to the Python
// backend on :7777 so the React app sees same-origin endpoints.
// Production: `vite build` emits to dist/, which Phase 9 wires into
// FastAPI's StaticFiles mount (single-origin, single-process kiosk).
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/chat": "http://localhost:7777",
            "/speak": "http://localhost:7777",
            "/transcribe": "http://localhost:7777",
            "/ping": "http://localhost:7777",
            "/profile": "http://localhost:7777",
            "/ws": { target: "ws://localhost:7777", ws: true },
        },
    },
    build: {
        outDir: "dist",
        sourcemap: true,
    },
});
