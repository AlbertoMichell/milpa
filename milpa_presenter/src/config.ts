// milpa_presenter/src/config.ts
// Config: valores por defecto sensibles según entorno (Docker vs. local dev).
import fs from 'fs';

function runningInDocker(): boolean {
  try { return fs.existsSync('/.dockerenv'); } catch { return false; }
}

const defaultIaUrl = runningInDocker() ? 'http://ai:8000' : 'http://127.0.0.1:8000';

export const config = {
  PORT: Number(process.env.PORT ?? 8080),
  IA_URL: process.env.IA_URL ?? defaultIaUrl,
  ALLOWED_ORIGINS: (process.env.ALLOWED_ORIGINS ?? "http://localhost:8080").split(","),
  MAX_CONCURRENCY: Number(process.env.MAX_CONCURRENCY ?? 8),
  QUEUE_CAPACITY: Number(process.env.QUEUE_CAPACITY ?? 64),
  /** Tiempo máximo para la mayoría de llamadas al backend (listados, query, etc.) */
  UPSTREAM_TIMEOUT_MS: Number(process.env.UPSTREAM_TIMEOUT_MS ?? 30000),
  /** Ingesta PDF, rebuild de índice, generación RAG: minutos, no segundos */
  UPSTREAM_TIMEOUT_LONG_MS: Number(process.env.UPSTREAM_TIMEOUT_LONG_MS ?? 600000),
  DEADLINE_MS: Number(process.env.DEADLINE_MS ?? 10000),
  CIRCUIT_OPEN_SECS: Number(process.env.CIRCUIT_OPEN_SECS ?? 20),
  /** El proxy incluye operaciones lentas; 3s de p95 abría el circuito sin fallo real */
  CIRCUIT_MAX_P95_MS: Number(process.env.CIRCUIT_MAX_P95_MS ?? 300000),
};
