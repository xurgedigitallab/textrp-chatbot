import fs from "node:fs";
import path from "node:path";

interface RedeemCacheValue {
  wallet: string;
  created_epoch: number;
  response: Record<string, unknown>;
}

interface RedeemCachePayload {
  version: number;
  records: Record<string, RedeemCacheValue>;
}

export class RedeemRequestStore {
  private readonly filePath: string;
  private cache: Record<string, RedeemCacheValue> = {};

  constructor(storageDir: string) {
    fs.mkdirSync(storageDir, { recursive: true });
    this.filePath = path.join(storageDir, "redeem_requests.json");
    this.load();
  }

  private load(): void {
    if (!fs.existsSync(this.filePath)) {
      this.persist();
      return;
    }
    try {
      const payload = JSON.parse(fs.readFileSync(this.filePath, "utf8")) as RedeemCachePayload;
      this.cache = payload.records ?? {};
    } catch {
      this.cache = {};
    }
  }

  private persist(): void {
    const payload: RedeemCachePayload = {
      version: 1,
      records: this.cache,
    };
    const tempPath = `${this.filePath}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2));
    fs.renameSync(tempPath, this.filePath);
  }

  get(wallet: string, key: string): Record<string, unknown> | null {
    const hit = this.cache[key];
    if (!hit || hit.wallet !== wallet) return null;
    return hit.response;
  }

  set(wallet: string, key: string, response: Record<string, unknown>, nowEpoch?: number): void {
    this.cache[key] = {
      wallet,
      response,
      created_epoch: nowEpoch ?? Math.trunc(Date.now() / 1000),
    };
    this.persist();
  }
}
