export class TransactionDeduplicator {
  private readonly maxEntries: number;
  private readonly seen = new Set<string>();
  private readonly queue: string[] = [];

  constructor(maxEntries = 10000) {
    this.maxEntries = maxEntries;
  }

  isDuplicate(txnId: string): boolean {
    if (this.seen.has(txnId)) return true;
    this.seen.add(txnId);
    this.queue.push(txnId);
    while (this.queue.length > this.maxEntries) {
      const dropped = this.queue.shift();
      if (dropped) this.seen.delete(dropped);
    }
    return false;
  }
}

