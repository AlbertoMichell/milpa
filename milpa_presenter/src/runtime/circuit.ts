export type CircuitState = 'closed' | 'half-open' | 'open';

export interface CircuitStats {
  state: CircuitState;
  lastOpenedAt: number | null;
}

export class CircuitBreaker {
  private state: CircuitState = 'closed';
  private lastOpenedAt: number | null = null;
  private recent: Array<{ ok: boolean; ms: number; at: number }> = [];

  constructor(private openSecs: number, private windowSize = 30, private maxP95Ms = 3000, private maxErrorRate = 0.4) {}

  get stats(): CircuitStats { return { state: this.state, lastOpenedAt: this.lastOpenedAt }; }

  allow(): boolean {
    if (this.state === 'open') {
      const since = this.lastOpenedAt ? (Date.now() - this.lastOpenedAt) / 1000 : Infinity;
      if (since >= this.openSecs) {
        this.state = 'half-open';
        return true; // permitir canarios
      }
      return false;
    }
    return true;
  }

  record(ok: boolean, ms: number) {
    const now = Date.now();
    this.recent.push({ ok, ms, at: now });
    if (this.recent.length > this.windowSize) this.recent.shift();

    // Calcular métricas en ventana
    const arr = this.recent.slice();
    const errors = arr.filter(r => !r.ok).length;
    const errRate = arr.length ? errors / arr.length : 0;
    const sorted = arr.map(r => r.ms).sort((a,b) => a-b);
    const p95 = sorted.length ? sorted[Math.min(sorted.length-1, Math.floor(sorted.length*0.95))] : 0;

    if (this.state === 'half-open') {
      // Si primer(s) intento(s) fallan o latencia alta, re-abrir
      if (!ok || p95 > this.maxP95Ms) {
        this.open();
      } else if (arr.length >= Math.min(5, this.windowSize)) {
        // suficientes buenos → cerrar
        this.state = 'closed';
      }
      return;
    }

    if (this.state === 'closed') {
      if (errRate > this.maxErrorRate || p95 > this.maxP95Ms) {
        this.open();
      }
    }
  }

  private open() {
    this.state = 'open';
    this.lastOpenedAt = Date.now();
  }
}
