import fs from "node:fs";
import path from "node:path";

export interface IdentityLink {
  wallet_address: string;
  matrix_user_id: string;
  xaman_account: string;
  created_epoch: number;
  updated_epoch: number;
}

interface IdentityLinkPayload {
  version: number;
  records: IdentityLink[];
}

export class IdentityLinkStore {
  private readonly filePath: string;
  private links: IdentityLink[] = [];

  constructor(storageDir: string) {
    fs.mkdirSync(storageDir, { recursive: true });
    this.filePath = path.join(storageDir, "identity_links.json");
    this.load();
  }

  private load(): void {
    if (!fs.existsSync(this.filePath)) {
      this.persist();
      return;
    }
    try {
      const payload = JSON.parse(fs.readFileSync(this.filePath, "utf8")) as IdentityLinkPayload;
      this.links = Array.isArray(payload.records) ? payload.records : [];
    } catch {
      this.links = [];
    }
  }

  private persist(): void {
    const payload: IdentityLinkPayload = {
      version: 1,
      records: this.links,
    };
    const tempPath = `${this.filePath}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2));
    fs.renameSync(tempPath, this.filePath);
  }

  upsertLink(input: {
    walletAddress: string;
    matrixUserId: string;
    xamanAccount: string;
    nowEpoch?: number;
  }): IdentityLink {
    const nowEpoch = input.nowEpoch ?? Math.trunc(Date.now() / 1000);
    const existing = this.links.find(
      (item) =>
        item.wallet_address === input.walletAddress ||
        item.matrix_user_id === input.matrixUserId ||
        item.xaman_account === input.xamanAccount,
    );
    if (existing) {
      existing.wallet_address = input.walletAddress;
      existing.matrix_user_id = input.matrixUserId;
      existing.xaman_account = input.xamanAccount;
      existing.updated_epoch = nowEpoch;
      this.persist();
      return existing;
    }
    const created: IdentityLink = {
      wallet_address: input.walletAddress,
      matrix_user_id: input.matrixUserId,
      xaman_account: input.xamanAccount,
      created_epoch: nowEpoch,
      updated_epoch: nowEpoch,
    };
    this.links.push(created);
    this.persist();
    return created;
  }

  getByWallet(walletAddress: string): IdentityLink | null {
    return this.links.find((item) => item.wallet_address === walletAddress) ?? null;
  }

  getByMatrixUserId(matrixUserId: string): IdentityLink | null {
    return this.links.find((item) => item.matrix_user_id === matrixUserId) ?? null;
  }
}
