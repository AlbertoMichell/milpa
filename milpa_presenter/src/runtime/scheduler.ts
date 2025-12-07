export type Task<T = any> = () => Promise<T>;

export interface SchedulerStats {
  inFlight: number;
  queued: number;
  maxConcurrency: number;
  queueCapacity: number;
}

export class Scheduler {
  private queue: Array<{ fn: Task; resolve: (v: any) => void; reject: (e: any) => void }> = [];
  private _inFlight = 0;
  constructor(private maxConcurrency: number, private queueCapacity: number) {}

  get stats(): SchedulerStats {
    return { inFlight: this._inFlight, queued: this.queue.length, maxConcurrency: this.maxConcurrency, queueCapacity: this.queueCapacity };
  }

  enqueue<T>(fn: Task<T>): Promise<T> {
    if (this.queue.length >= this.queueCapacity) {
      return Promise.reject(new Error('queue_full'));
    }
    return new Promise<T>((resolve, reject) => {
      this.queue.push({ fn, resolve, reject });
      this.drain();
    });
  }

  private drain() {
    while (this._inFlight < this.maxConcurrency && this.queue.length > 0) {
      const item = this.queue.shift()!;
      this._inFlight++;
      item.fn()
        .then((v: any) => item.resolve(v))
        .catch((e: any) => item.reject(e))
        .finally(() => {
          this._inFlight--;
          this.drain();
        });
    }
  }
}
