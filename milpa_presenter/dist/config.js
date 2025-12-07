// milpa_presenter/src/config.ts
// Config: valores por defecto sensibles según entorno (Docker vs. local dev).
import fs from 'fs';
function runningInDocker() {
    try {
        return fs.existsSync('/.dockerenv');
    }
    catch {
        return false;
    }
}
const defaultIaUrl = runningInDocker() ? 'http://ai:8000' : 'http://127.0.0.1:8000';
export const config = {
    PORT: Number(process.env.PORT ?? 8080),
    IA_URL: process.env.IA_URL ?? defaultIaUrl,
    ALLOWED_ORIGINS: (process.env.ALLOWED_ORIGINS ?? "https://dashboard.milpa").split(","),
    MAX_CONCURRENCY: Number(process.env.MAX_CONCURRENCY ?? 8),
    QUEUE_CAPACITY: Number(process.env.QUEUE_CAPACITY ?? 64),
    UPSTREAM_TIMEOUT_MS: Number(process.env.UPSTREAM_TIMEOUT_MS ?? 9000),
    DEADLINE_MS: Number(process.env.DEADLINE_MS ?? 10000),
    CIRCUIT_OPEN_SECS: Number(process.env.CIRCUIT_OPEN_SECS ?? 20),
};
