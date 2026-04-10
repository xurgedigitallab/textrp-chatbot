import fs from "node:fs";
import path from "node:path";

export interface InAppNotification {
  id: number;
  wallet: string;
  title: string;
  message: string;
  type: string;
  created_epoch: number;
  deliver_epoch: number;
  read_epoch: number;
}

interface InAppNotificationPayload {
  version: number;
  next_id: number;
  records: InAppNotification[];
}

export class InAppNotificationStore {
  private readonly filePath: string;
  private notifications: InAppNotification[] = [];
  private nextId = 1;

  constructor(storageDir: string) {
    fs.mkdirSync(storageDir, { recursive: true });
    this.filePath = path.join(storageDir, "in_app_notifications.json");
    this.load();
  }

  private load(): void {
    if (!fs.existsSync(this.filePath)) {
      this.persist();
      return;
    }
    try {
      const payload = JSON.parse(fs.readFileSync(this.filePath, "utf8")) as InAppNotificationPayload;
      this.nextId = Number(payload.next_id ?? 1);
      this.notifications = Array.isArray(payload.records) ? payload.records : [];
    } catch {
      this.nextId = 1;
      this.notifications = [];
    }
  }

  private persist(): void {
    const payload: InAppNotificationPayload = {
      version: 1,
      next_id: this.nextId,
      records: this.notifications,
    };
    const tempPath = `${this.filePath}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2));
    fs.renameSync(tempPath, this.filePath);
  }

  createNotification(input: {
    wallet: string;
    title: string;
    message: string;
    type: string;
    deliverEpoch?: number;
    nowEpoch?: number;
  }): InAppNotification {
    const nowEpoch = input.nowEpoch ?? Math.trunc(Date.now() / 1000);
    const created: InAppNotification = {
      id: this.nextId,
      wallet: input.wallet,
      title: input.title,
      message: input.message,
      type: input.type,
      created_epoch: nowEpoch,
      deliver_epoch: input.deliverEpoch ?? nowEpoch,
      read_epoch: 0,
    };
    this.nextId += 1;
    this.notifications.push(created);
    this.persist();
    return created;
  }

  listVisible(wallet: string, nowEpoch?: number): InAppNotification[] {
    const now = nowEpoch ?? Math.trunc(Date.now() / 1000);
    return this.notifications
      .filter((item) => item.wallet === wallet && item.deliver_epoch <= now)
      .sort((a, b) => b.created_epoch - a.created_epoch);
  }

  markRead(wallet: string, ids: number[] | "all", nowEpoch?: number): number {
    const now = nowEpoch ?? Math.trunc(Date.now() / 1000);
    const target = ids === "all" ? null : new Set(ids);
    let changed = 0;
    for (const item of this.notifications) {
      if (item.wallet !== wallet) continue;
      if (item.read_epoch > 0) continue;
      if (target && !target.has(item.id)) continue;
      item.read_epoch = now;
      changed += 1;
    }
    if (changed > 0) this.persist();
    return changed;
  }
}
