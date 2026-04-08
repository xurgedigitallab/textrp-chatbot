import fs from "node:fs";
import path from "node:path";

const JSON_VERSION = 1;

export type EpochProvider = () => Promise<number>;
type EpochLike = number | string | Date;

interface ClaimRecord {
  wallet: string;
  last_claim_epoch: number;
  claim_count: number;
  total_claimed: string;
  first_claim_epoch: number;
  last_tx_hash: string;
}

interface UserPreferences {
  wallet: string;
  reminders_enabled: boolean;
  reminder_offset: number;
  timezone: string;
  created_epoch: number;
  updated_epoch: number;
}

interface ReminderRecord {
  id: number;
  wallet: string;
  room_id: string;
  reminder_epoch: number;
  message: string;
  sent: boolean;
  created_epoch: number;
  sent_epoch: number;
}

interface FaucetStats {
  id: 1;
  total_claims: number;
  total_distributed: string;
  unique_wallets: number;
  last_updated_epoch: number;
}

interface StoreFiles {
  claimsFile: string;
  blacklistFile: string;
  faucetStatsFile: string;
  roomJoinsFile: string;
  userPreferencesFile: string;
  remindersFile: string;
  migrationMetadataFile: string;
  initMarkerFile: string;
}

function toIso(epoch: number): string {
  return new Date(Math.max(epoch, 0) * 1000).toISOString().replace("Z", "");
}

function parseEpoch(value: EpochLike | undefined): number | null {
  if (value == null) return null;
  if (typeof value === "number") return Math.trunc(value);
  if (value instanceof Date) return Math.trunc(value.getTime() / 1000);
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (/^-?\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
    const parsed = Date.parse(trimmed);
    if (!Number.isNaN(parsed)) return Math.trunc(parsed / 1000);
  }
  return null;
}

function normalizeAmount(value: unknown): string {
  const asNum = Number.parseFloat(String(value));
  if (Number.isNaN(asNum)) return "0";
  return asNum.toString();
}

function addAmounts(a: unknown, b: unknown): string {
  const total = Number.parseFloat(String(a)) + Number.parseFloat(String(b));
  if (Number.isNaN(total)) return "0";
  return total.toString();
}

function readJsonObject<T extends Record<string, unknown>>(filePath: string, fallback: T): T {
  if (!fs.existsSync(filePath)) return { ...fallback };
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed as T;
  } catch {
    return { ...fallback };
  }
  return { ...fallback };
}

function writeJsonAtomic(filePath: string, payload: Record<string, unknown>): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2));
  fs.renameSync(tempPath, filePath);
}

function resolvePaths(configuredPath: string): { storageDir: string; legacySqlitePath: string } {
  const hasSuffix = path.extname(configuredPath) !== "";
  if (fs.existsSync(configuredPath) && fs.statSync(configuredPath).isFile()) {
    return {
      storageDir: path.join(path.dirname(configuredPath), `${path.basename(configuredPath, path.extname(configuredPath))}_store`),
      legacySqlitePath: configuredPath,
    };
  }

  if (hasSuffix) {
    return {
      storageDir: path.join(path.dirname(configuredPath), path.basename(configuredPath, path.extname(configuredPath))),
      legacySqlitePath: configuredPath,
    };
  }

  return {
    storageDir: configuredPath,
    legacySqlitePath: `${configuredPath}.db`,
  };
}

export class FaucetStore {
  private readonly cooldownHours: number;
  private readonly epochProvider: EpochProvider;
  private readonly files: StoreFiles;
  private readonly storageDir: string;
  private readonly legacySqlitePath: string;

  private claims: Record<string, ClaimRecord> = {};
  private blacklist: Record<string, { wallet: string; reason: string; blacklisted_epoch: number; blacklisted_by: string }> = {};
  private faucetStats: FaucetStats = {
    id: 1,
    total_claims: 0,
    total_distributed: "0",
    unique_wallets: 0,
    last_updated_epoch: 0,
  };
  private roomJoins: Record<string, { room_id: string; joined_epoch: number; welcome_sent: boolean; room_name?: string }> = {};
  private userPreferences: Record<string, UserPreferences> = {};
  private scheduledReminders: ReminderRecord[] = [];
  private nextReminderId = 1;

  constructor(config: { dbPath: string; cooldownHours: number; epochProvider: EpochProvider }) {
    this.cooldownHours = config.cooldownHours;
    this.epochProvider = config.epochProvider;
    const resolved = resolvePaths(config.dbPath);
    this.storageDir = resolved.storageDir;
    this.legacySqlitePath = resolved.legacySqlitePath;
    fs.mkdirSync(this.storageDir, { recursive: true });

    this.files = {
      claimsFile: path.join(this.storageDir, "claims.json"),
      blacklistFile: path.join(this.storageDir, "blacklist.json"),
      faucetStatsFile: path.join(this.storageDir, "faucet_stats.json"),
      roomJoinsFile: path.join(this.storageDir, "room_joins.json"),
      userPreferencesFile: path.join(this.storageDir, "user_preferences.json"),
      remindersFile: path.join(this.storageDir, "scheduled_reminders.json"),
      migrationMetadataFile: path.join(this.storageDir, "migration_metadata.json"),
      initMarkerFile: path.join(this.storageDir, ".json_store_initialized"),
    };

    this.initStorage();
  }

  private initStorage(): void {
    const claimsPayload = readJsonObject(this.files.claimsFile, { records: {} as Record<string, ClaimRecord> });
    this.claims = claimsPayload.records ?? {};

    const blacklistPayload = readJsonObject(this.files.blacklistFile, {
      records: {} as Record<string, { wallet: string; reason: string; blacklisted_epoch: number; blacklisted_by: string }>,
    });
    this.blacklist = blacklistPayload.records ?? {};

    const statsPayload = readJsonObject(this.files.faucetStatsFile, this.faucetStats as unknown as Record<string, unknown>);
    this.faucetStats = {
      id: 1,
      total_claims: Number(statsPayload.total_claims ?? 0),
      total_distributed: normalizeAmount(statsPayload.total_distributed ?? "0"),
      unique_wallets: Number(statsPayload.unique_wallets ?? 0),
      last_updated_epoch: Number(statsPayload.last_updated_epoch ?? 0),
    };

    const roomPayload = readJsonObject(this.files.roomJoinsFile, { records: {} as typeof this.roomJoins });
    this.roomJoins = roomPayload.records ?? {};

    const prefsPayload = readJsonObject(this.files.userPreferencesFile, { records: {} as Record<string, UserPreferences> });
    this.userPreferences = prefsPayload.records ?? {};

    const remindersPayload = readJsonObject(this.files.remindersFile, { next_id: 1, records: [] as ReminderRecord[] });
    this.nextReminderId = Number(remindersPayload.next_id ?? 1);
    this.scheduledReminders = remindersPayload.records ?? [];

    if (!fs.existsSync(this.files.initMarkerFile)) {
      writeJsonAtomic(this.files.migrationMetadataFile, {
        version: JSON_VERSION,
        source: this.legacySqlitePath,
        migrated: false,
      });
      writeJsonAtomic(this.files.initMarkerFile, { version: JSON_VERSION, initialized: true });
    }

    this.persistAll();
  }

  private persistAll(): void {
    writeJsonAtomic(this.files.claimsFile, { version: JSON_VERSION, records: this.claims });
    writeJsonAtomic(this.files.blacklistFile, { version: JSON_VERSION, records: this.blacklist });
    writeJsonAtomic(this.files.faucetStatsFile, { version: JSON_VERSION, ...this.faucetStats });
    writeJsonAtomic(this.files.roomJoinsFile, { version: JSON_VERSION, records: this.roomJoins });
    writeJsonAtomic(this.files.userPreferencesFile, { version: JSON_VERSION, records: this.userPreferences });
    writeJsonAtomic(this.files.remindersFile, {
      version: JSON_VERSION,
      next_id: this.nextReminderId,
      records: this.scheduledReminders,
    });
  }

  private async currentEpoch(): Promise<number> {
    const epoch = await this.epochProvider();
    const parsed = parseEpoch(epoch);
    if (parsed == null) throw new Error("Invalid deterministic epoch value");
    return parsed;
  }

  async checkClaimEligibility(wallet: string): Promise<{ eligible: boolean; reason?: string }> {
    if (this.blacklist[wallet]) return { eligible: false, reason: "Wallet is blacklisted from faucet" };

    try {
      const nowEpoch = await this.currentEpoch();
      const claim = this.claims[wallet];
      if (claim) {
        const elapsed = nowEpoch - Number(claim.last_claim_epoch);
        const cooldown = this.cooldownHours * 3600;
        if (elapsed < cooldown) {
          const hoursRemaining = (cooldown - elapsed) / 3600;
          return { eligible: false, reason: `Please wait ${hoursRemaining.toFixed(1)} hours before claiming again` };
        }
      }
      return { eligible: true };
    } catch {
      return { eligible: false, reason: "Deterministic time source unavailable" };
    }
  }

  async recordClaim(wallet: string, amount: string, txHash: string, eventEpoch?: number): Promise<boolean> {
    try {
      const nowEpoch = eventEpoch ?? (await this.currentEpoch());
      const claim = this.claims[wallet];

      if (claim) {
        claim.claim_count += 1;
        claim.total_claimed = addAmounts(claim.total_claimed, amount);
        claim.last_claim_epoch = nowEpoch;
        claim.last_tx_hash = txHash;
      } else {
        this.claims[wallet] = {
          wallet,
          last_claim_epoch: nowEpoch,
          claim_count: 1,
          total_claimed: normalizeAmount(amount),
          first_claim_epoch: nowEpoch,
          last_tx_hash: txHash,
        };
        this.faucetStats.unique_wallets += 1;
      }

      this.faucetStats.total_claims += 1;
      this.faucetStats.total_distributed = addAmounts(this.faucetStats.total_distributed, amount);
      this.faucetStats.last_updated_epoch = nowEpoch;
      this.persistAll();
      return true;
    } catch {
      return false;
    }
  }

  async getUserClaimHistory(wallet: string): Promise<Array<Record<string, unknown>>> {
    const claim = this.claims[wallet];
    if (!claim) return [];
    return [
      {
        last_claim: toIso(claim.last_claim_epoch),
        claim_count: claim.claim_count,
        total_claimed: claim.total_claimed,
        last_tx_hash: claim.last_tx_hash,
        first_claim: toIso(claim.first_claim_epoch),
      },
    ];
  }

  async recordRoomJoin(roomId: string, roomName?: string): Promise<boolean> {
    try {
      const now = await this.currentEpoch();
      this.roomJoins[roomId] = {
        room_id: roomId,
        joined_epoch: now,
        welcome_sent: false,
        room_name: roomName,
      };
      this.persistAll();
      return true;
    } catch {
      return false;
    }
  }

  async markWelcomeSent(roomId: string): Promise<boolean> {
    const room = this.roomJoins[roomId];
    if (room) {
      room.welcome_sent = true;
      this.persistAll();
    }
    return true;
  }

  async getUserPreferences(wallet: string): Promise<Record<string, unknown> | null> {
    const prefs = this.userPreferences[wallet];
    if (!prefs) return null;
    return {
      reminders_enabled: prefs.reminders_enabled,
      reminder_offset: prefs.reminder_offset,
      timezone: prefs.timezone,
      created_at: toIso(prefs.created_epoch),
      updated_at: toIso(prefs.updated_epoch),
    };
  }

  async setUserPreferences(wallet: string, patch: Partial<UserPreferences>): Promise<boolean> {
    try {
      const now = await this.currentEpoch();
      const existing = this.userPreferences[wallet];
      if (!existing) {
        this.userPreferences[wallet] = {
          wallet,
          reminders_enabled: patch.reminders_enabled ?? true,
          reminder_offset: patch.reminder_offset ?? 1,
          timezone: patch.timezone ?? "UTC",
          created_epoch: now,
          updated_epoch: now,
        };
      } else {
        existing.reminders_enabled = patch.reminders_enabled ?? existing.reminders_enabled;
        existing.reminder_offset = patch.reminder_offset ?? existing.reminder_offset;
        existing.timezone = patch.timezone ?? existing.timezone;
        existing.updated_epoch = now;
      }
      this.persistAll();
      return true;
    } catch {
      return false;
    }
  }

  async scheduleReminder(wallet: string, roomId: string, reminderTime: EpochLike, message: string): Promise<boolean> {
    const now = await this.currentEpoch();
    const reminderEpoch = parseEpoch(reminderTime);
    if (reminderEpoch == null) return false;
    this.scheduledReminders.push({
      id: this.nextReminderId,
      wallet,
      room_id: roomId,
      reminder_epoch: reminderEpoch,
      message,
      sent: false,
      created_epoch: now,
      sent_epoch: 0,
    });
    this.nextReminderId += 1;
    this.persistAll();
    return true;
  }

  async getPendingReminders(beforeTime?: EpochLike): Promise<Array<Record<string, unknown>>> {
    const beforeEpoch = beforeTime == null ? await this.currentEpoch() : parseEpoch(beforeTime);
    if (beforeEpoch == null) return [];
    return this.scheduledReminders
      .filter((reminder) => !reminder.sent && reminder.reminder_epoch <= beforeEpoch)
      .sort((a, b) => a.reminder_epoch - b.reminder_epoch)
      .map((reminder) => ({
        id: reminder.id,
        wallet: reminder.wallet,
        room_id: reminder.room_id,
        reminder_time: toIso(reminder.reminder_epoch),
        message: reminder.message,
      }));
  }

  async markReminderSent(reminderId: number): Promise<boolean> {
    const now = await this.currentEpoch();
    const reminder = this.scheduledReminders.find((item) => item.id === reminderId);
    if (reminder) {
      reminder.sent = true;
      reminder.sent_epoch = now;
      this.persistAll();
    }
    return true;
  }

  getStorageDir(): string {
    return this.storageDir;
  }
}

