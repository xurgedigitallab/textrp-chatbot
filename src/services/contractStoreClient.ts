import { randomUUID } from "node:crypto";
import * as HotPocket from "hotpocket-js-client";

import type { ClaimEligibilityResult, FaucetStateStore, UserPreferencesPatch } from "./faucetStateStore.js";

type RpcRequest = {
  v: 1;
  id: string;
  cmd: string;
  [key: string]: unknown;
};

type RpcResponse = {
  v: number;
  id: string | null;
  ok: boolean;
  cmd: string;
  data?: Record<string, unknown>;
  error?: { code?: string; message?: string };
};

type ContractOutputEvent = {
  outputs?: RpcResponse[];
  ledgerSeqNo?: number;
};

type HotPocketClient = Awaited<ReturnType<typeof HotPocket.createClient>>;

export class ContractStoreClient implements FaucetStateStore {
  private readonly servers: string[];
  private readonly timeoutMs: number;
  private readonly cooldownHours: number;
  private client?: HotPocketClient;
  private readonly pending = new Map<string, (response: RpcResponse) => void>();
  private connected = false;

  constructor(config: { servers: string[]; timeoutMs?: number; cooldownHours: number }) {
    this.servers = config.servers;
    this.timeoutMs = config.timeoutMs ?? 15_000;
    this.cooldownHours = config.cooldownHours;
  }

  async start(): Promise<void> {
    if (this.connected) return;
    if (this.servers.length === 0) {
      throw new Error("No HotPocket contract servers configured");
    }

    const keyPair = await HotPocket.generateKeys();
    const connectionAttempts = [this.servers, ...this.servers.map((server) => [server])];
    const seen = new Set<string>();
    const errors: string[] = [];

    for (const attemptServers of connectionAttempts) {
      const attemptKey = attemptServers.join(",");
      if (seen.has(attemptKey)) continue;
      seen.add(attemptKey);

      let attemptClient: HotPocketClient | undefined;
      try {
        attemptClient = await HotPocket.createClient(attemptServers, keyPair);
        this.attachClientHandlers(attemptClient);
        const connected = await attemptClient.connect();
        if (connected) {
          this.client = attemptClient;
          this.connected = true;
          return;
        }
        errors.push(`[${attemptKey}] connect() returned false`);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        errors.push(`[${attemptKey}] ${message}`);
      } finally {
        if (attemptClient && !this.connected) {
          attemptClient.close();
        }
      }
    }

    throw new Error(`Failed to connect to HotPocket contract. Attempts: ${errors.join("; ")}`);
  }

  private attachClientHandlers(client: HotPocketClient): void {
    client.on(HotPocket.events.contractOutput, (event: ContractOutputEvent) => {
      for (const output of event.outputs ?? []) {
        if (output && typeof output.id === "string") {
          const resolver = this.pending.get(output.id);
          if (resolver) {
            this.pending.delete(output.id);
            resolver(output);
          }
        }
      }
    });

    client.on(HotPocket.events.disconnect, () => {
      this.connected = false;
      for (const [, resolver] of this.pending) {
        resolver({
          v: 1,
          id: null,
          ok: false,
          cmd: "disconnect",
          error: { code: "DISCONNECTED", message: "HotPocket client disconnected" },
        });
      }
      this.pending.clear();
    });
  }

  async stop(): Promise<void> {
    if (!this.client) return;
    this.client.close();
    this.connected = false;
  }

  private async rpcRead(cmd: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    if (!this.client || !this.connected) throw new Error("Contract client is not connected");
    const request: RpcRequest = { v: 1, id: randomUUID(), cmd, ...payload };
    const output = (await this.client.submitContractReadRequest(JSON.stringify(request))) as RpcResponse;
    return this.unwrapResponse(output, cmd);
  }

  private async rpcWrite(cmd: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    if (!this.client || !this.connected) throw new Error("Contract client is not connected");
    const requestId = randomUUID();
    const request: RpcRequest = { v: 1, id: requestId, cmd, ...payload };

    const waitForOutput = new Promise<RpcResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Timeout waiting for contract output for ${cmd}`));
      }, this.timeoutMs);

      this.pending.set(requestId, (response) => {
        clearTimeout(timer);
        resolve(response);
      });
    });

    const submission = await this.client.submitContractInput(JSON.stringify(request));
    const status = await submission.submissionStatus;
    if (status.status !== "accepted") {
      this.pending.delete(requestId);
      throw new Error(`Contract submission rejected: ${status.reason ?? "unknown reason"}`);
    }

    const output = await waitForOutput;
    return this.unwrapResponse(output, cmd);
  }

  private unwrapResponse(output: RpcResponse, cmd: string): Record<string, unknown> {
    if (!output || output.ok !== true) {
      const code = output?.error?.code ?? "RPC_ERROR";
      const message = output?.error?.message ?? `Contract command failed: ${cmd}`;
      throw new Error(`${code}: ${message}`);
    }
    return output.data ?? {};
  }

  async checkClaimEligibility(wallet: string): Promise<ClaimEligibilityResult> {
    const data = await this.rpcRead("claim.eligibility", { wallet });
    const secondsRemainingRaw = data.seconds_remaining;
    const secondsRemaining =
      typeof secondsRemainingRaw === "number" && Number.isFinite(secondsRemainingRaw)
        ? Math.max(0, Math.trunc(secondsRemainingRaw))
        : undefined;
    return {
      eligible: Boolean(data.eligible),
      reason: typeof data.reason === "string" ? data.reason : undefined,
      secondsRemaining,
    };
  }

  async recordClaim(wallet: string, amount: string, txHash: string, _eventEpoch?: number): Promise<boolean> {
    await this.rpcWrite("claim.record", { wallet, amount, tx_hash: txHash });
    return true;
  }

  async getUserClaimHistory(wallet: string): Promise<Array<Record<string, unknown>>> {
    const data = await this.rpcRead("claim.history", { wallet });
    const history = data.history;
    return Array.isArray(history) ? history.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object")) : [];
  }

  async recordRoomJoin(roomId: string, roomName?: string): Promise<boolean> {
    await this.rpcWrite("room.join", { room_id: roomId, room_name: roomName });
    return true;
  }

  async markWelcomeSent(roomId: string): Promise<boolean> {
    await this.rpcWrite("room.welcome_sent", { room_id: roomId });
    return true;
  }

  async getUserPreferences(wallet: string): Promise<Record<string, unknown> | null> {
    const data = await this.rpcRead("prefs.get", { wallet });
    const preferences = data.preferences;
    if (!preferences || typeof preferences !== "object") return null;
    return preferences as Record<string, unknown>;
  }

  async setUserPreferences(wallet: string, patch: UserPreferencesPatch): Promise<boolean> {
    await this.rpcWrite("prefs.set", { wallet, patch });
    return true;
  }

  async scheduleReminder(wallet: string, roomId: string, reminderTime: number, message: string): Promise<boolean> {
    await this.rpcWrite("reminder.schedule", {
      wallet,
      room_id: roomId,
      reminder_epoch: Math.trunc(reminderTime),
      message,
    });
    return true;
  }

  async scheduleClaimReminder(wallet: string, roomId: string, offsetHours: number, message: string): Promise<boolean> {
    await this.rpcWrite("reminder.schedule", {
      wallet,
      room_id: roomId,
      cooldown_hours: this.cooldownHours,
      offset_hours: offsetHours,
      message,
    });
    return true;
  }

  async getPendingReminders(beforeTime?: number): Promise<Array<Record<string, unknown>>> {
    const data = await this.rpcRead("reminders.pending", beforeTime == null ? {} : { before_epoch: Math.trunc(beforeTime) });
    const reminders = data.reminders;
    return Array.isArray(reminders)
      ? reminders.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object"))
      : [];
  }

  async markReminderSent(reminderId: number): Promise<boolean> {
    await this.rpcWrite("reminder.mark_sent", { reminder_id: reminderId });
    return true;
  }
}
