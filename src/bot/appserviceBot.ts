import path from "node:path";
import {
  Appservice,
  AutojoinRoomsMixin,
  SimpleFsStorageProvider,
  SimpleRetryJoinStrategy,
} from "matrix-bot-sdk";
import * as xrpl from "xrpl";

import type { BotConfig } from "../config.js";
import { CommandRouter } from "./commandRouter.js";
import { ContractStoreClient } from "../services/contractStoreClient.js";
import type { FaucetStateStore } from "../services/faucetStateStore.js";
import { XRPL_UNIX_EPOCH_OFFSET, XrplService } from "../services/xrplClient.js";
import { InAppNotificationStore } from "../storage/inAppNotificationStore.js";
import { IdentityLinkStore } from "../storage/identityLinkStore.js";
import { NotificationService } from "../notifications/notificationService.js";
import { FaucetCoreService } from "../domain/faucetCoreService.js";

const SECP256K1_ALGORITHM = ((xrpl as any).ECDSA?.secp256k1 ?? "ecdsa-secp256k1") as any;

interface RoomMemberRecord {
  roomId: string;
  userId: string;
}

export class AppserviceBot {
  private readonly config: BotConfig;
  private readonly xrpl: XrplService;
  private readonly faucetStore: FaucetStateStore;
  private readonly contractStoreClient: ContractStoreClient;
  private readonly appservice: Appservice;
  private readonly commandRouter: CommandRouter;
  private readonly identityLinkStore: IdentityLinkStore;
  private readonly notificationService: NotificationService;
  private readonly faucetCore: FaucetCoreService;
  private readonly knownMembership = new Map<string, Set<string>>();
  private reminderTimer?: NodeJS.Timeout;
  private stopping = false;

  constructor(config: BotConfig) {
    this.config = config;
    this.xrpl = new XrplService({
      network: config.xrplNetwork,
      rpcUrl: config.xrplRpcUrl,
      lpInfo: config.lpInfo,
    });

    this.contractStoreClient = new ContractStoreClient({
      servers: config.hpContractServers,
      timeoutMs: config.hpContractTimeoutMs,
      cooldownHours: config.faucetCooldownHours,
    });
    this.faucetStore = this.contractStoreClient;
    const inAppStore = new InAppNotificationStore(config.xappStorageDir);
    this.identityLinkStore = new IdentityLinkStore(config.xappStorageDir);
    this.notificationService = new NotificationService(this.faucetStore, inAppStore);
    this.faucetCore = new FaucetCoreService(
      {
        faucetCurrencyCode: config.faucetCurrencyCode,
        faucetCooldownHours: config.faucetCooldownHours,
        faucetDailyAmount: config.faucetDailyAmount,
        faucetMinXrpBalance: config.faucetMinXrpBalance,
        tokenIssuer: config.tokenIssuer,
        faucetWalletSeed: config.faucetWalletSeed,
        commandPrefix: config.commandPrefix,
      },
      this.faucetStore,
      this.xrpl,
      this.notificationService,
    );

    const usernameParts = config.textrpUsername.split(":");
    const homeserverName = usernameParts.length > 1 ? usernameParts[1] : "";
    const senderUserRegex = `@${config.matrixAsSenderLocalpart}.+:${homeserverName.replace(/\./g, "\\.")}`;
    const registration = {
      id: config.matrixAsId,
      as_token: config.matrixAsToken,
      hs_token: config.matrixHsToken,
      sender_localpart: config.matrixAsSenderLocalpart,
      rate_limited: false,
      namespaces: {
        users: [{ exclusive: true, regex: senderUserRegex }],
        aliases: [],
        rooms: [],
      },
      url: config.matrixAsUrl,
      "de.sorunome.msc2409.push_ephemeral": true,
    };

    this.appservice = new Appservice({
      bindAddress: config.matrixAsHost,
      port: config.matrixAsPort,
      homeserverName,
      homeserverUrl: config.textrpHomeserver,
      registration,
      storage: new SimpleFsStorageProvider(path.resolve(".matrix-appservice-storage.json")),
      joinStrategy: new SimpleRetryJoinStrategy(),
    });

    this.commandRouter = new CommandRouter({
      botUserId: config.textrpUsername,
      commandPrefix: config.commandPrefix,
      faucetCurrencyCode: config.faucetCurrencyCode,
      faucetCooldownHours: config.faucetCooldownHours,
      faucetDailyAmount: config.faucetDailyAmount,
      faucetMinXrpBalance: config.faucetMinXrpBalance,
      tokenIssuer: config.tokenIssuer,
      faucetWalletSeed: config.faucetWalletSeed,
      faucetStore: this.faucetStore,
      xrpl: this.xrpl,
      getDeterministicEpoch: async () => this.getDeterministicEpoch(),
      faucetCore: this.faucetCore,
      resolveWalletForSender: async (sender) => this.identityLinkStore.getByMatrixUserId(sender)?.wallet_address ?? null,
      sendMessage: async (roomId, body) => {
        const client = this.appservice.botIntent.underlyingClient;
        await client.sendMessage(roomId, { msgtype: "m.text", body });
      },
      sendTyping: async (roomId, typing) => {
        const client = this.appservice.botIntent.underlyingClient;
        await client.setTyping(roomId, typing, 5000);
      },
      resolveDmRoom: async (sender) => {
        const client = this.appservice.botIntent.underlyingClient;
        const roomId = await client.createRoom({
          is_direct: true,
          invite: [sender],
          preset: "trusted_private_chat",
        });
        this.trackMembership({ roomId, userId: sender });
        return roomId;
      },
      resolveRoomMemberCount: async (roomId) => this.estimateRoomSize(roomId),
    });

    AutojoinRoomsMixin.setupOnAppservice(this.appservice);
    this.registerListeners();
  }

  private registerListeners(): void {
    this.appservice.on("room.message", async (roomId: string, event: Record<string, unknown>) => {
      await this.commandRouter.handleMessage(roomId, {
        sender: String(event.sender ?? ""),
        content: event.content as { msgtype?: string; body?: string },
      });
    });

    this.appservice.on("room.event", async (roomId: string, event: Record<string, unknown>) => {
      if (event.type !== "m.room.member") return;
      const membership = (event.content as Record<string, unknown> | undefined)?.membership;
      const stateKey = String(event.state_key ?? "");
      if (membership === "join" && stateKey) {
        this.trackMembership({ roomId, userId: stateKey });
      }
      if (membership === "invite" && stateKey === this.config.textrpUsername) {
        await this.faucetStore.recordRoomJoin(roomId);
        await this.sendWelcome(roomId);
      }
    });
  }

  private trackMembership(record: RoomMemberRecord): void {
    if (!this.knownMembership.has(record.roomId)) {
      this.knownMembership.set(record.roomId, new Set());
    }
    this.knownMembership.get(record.roomId)?.add(record.userId);
  }

  private async estimateRoomSize(roomId: string): Promise<number> {
    const known = this.knownMembership.get(roomId);
    if (known && known.size > 0) return known.size;
    try {
      const client = this.appservice.botIntent.underlyingClient;
      const joined = await client.getJoinedRoomMembers(roomId);
      const members = Array.isArray(joined) ? joined : [];
      if (members.length > 0) {
        this.knownMembership.set(roomId, new Set(members));
      }
      return members.length;
    } catch {
      return 0;
    }
  }

  private async sendWelcome(roomId: string): Promise<void> {
    const body = [
      "Welcome to the TextRP faucet bot.",
      `Use ${this.config.commandPrefix}help to list commands.`,
      `Use ${this.config.commandPrefix}trust before ${this.config.commandPrefix}faucet.`,
    ].join("\n");
    await this.appservice.botIntent.underlyingClient.sendMessage(roomId, { msgtype: "m.text", body });
    await this.faucetStore.markWelcomeSent(roomId);
  }

  private async getDeterministicEpoch(): Promise<number> {
    const ledger = await this.xrpl.getLedgerInfo("validated");
    if (!ledger || typeof ledger.close_time !== "number") {
      throw new Error("Validated XRPL ledger close_time unavailable");
    }
    return Number(ledger.close_time) + XRPL_UNIX_EPOCH_OFFSET;
  }

  private startReminderLoop(): void {
    this.reminderTimer = setInterval(async () => {
      if (this.stopping) return;
      const reminders = await this.faucetStore.getPendingReminders();
      for (const reminder of reminders) {
        const roomId = String(reminder.room_id ?? "");
        const message = String(reminder.message ?? "");
        const reminderId = Number(reminder.id ?? 0);
        if (!roomId || !message || !reminderId) continue;
        await this.appservice.botIntent.underlyingClient.sendMessage(roomId, { msgtype: "m.text", body: message });
        await this.faucetStore.markReminderSent(reminderId);
      }
    }, 60_000);
  }

  async start(): Promise<void> {
    await this.xrpl.connect();
    await this.contractStoreClient.start();
    await this.appservice.begin();
    this.startReminderLoop();
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.reminderTimer) clearInterval(this.reminderTimer);
    await this.xrpl.disconnect();
    await this.contractStoreClient.stop();
    await this.appservice.stop();
  }

  faucetWalletAddress(): string | null {
    if (!this.config.faucetWalletSeed) return null;
    try {
      return xrpl.Wallet.fromSeed(this.config.faucetWalletSeed, { algorithm: SECP256K1_ALGORITHM }).classicAddress;
    } catch {
      return null;
    }
  }

  getFaucetCoreService(): FaucetCoreService {
    return this.faucetCore;
  }

  getNotificationService(): NotificationService {
    return this.notificationService;
  }

  getIdentityLinkStore(): IdentityLinkStore {
    return this.identityLinkStore;
  }
}

