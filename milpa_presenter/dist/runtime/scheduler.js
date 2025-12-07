export class Scheduler {
    maxConcurrency;
    queueCapacity;
    queue = [];
    _inFlight = 0;
    constructor(maxConcurrency, queueCapacity) {
        this.maxConcurrency = maxConcurrency;
        this.queueCapacity = queueCapacity;
    }
    get stats() {
        return { inFlight: this._inFlight, queued: this.queue.length, maxConcurrency: this.maxConcurrency, queueCapacity: this.queueCapacity };
    }
    enqueue(fn) {
        if (this.queue.length >= this.queueCapacity) {
            return Promise.reject(new Error('queue_full'));
        }
        return new Promise((resolve, reject) => {
            this.queue.push({ fn, resolve, reject });
            this.drain();
        });
    }
    drain() {
        while (this._inFlight < this.maxConcurrency && this.queue.length > 0) {
            const item = this.queue.shift();
            this._inFlight++;
            item.fn()
                .then((v) => item.resolve(v))
                .catch((e) => item.reject(e))
                .finally(() => {
                this._inFlight--;
                this.drain();
            });
        }
    }
}
