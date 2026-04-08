import { FaucetStore } from "../services/faucetStore.js";
import { FAUCET_BALANCE_FACTOR, XrplService } from "../services/xrplClient.js";
import { shortHash, extractWalletFromUserId } from "../utils/wallet.js";
import * as xrpl from "xrpl";

type CommandHandler = (context: CommandContext) => Promise<void>;

interface MatrixMessageEvent {
  sender: string;
  content?: {
    msgtype?: string;
    body?: string;
  };
}

interface CommandContext {
  roomId: string;
  sender: string;
  args: string;
  replyRoomId: string;
}

export interface CommandRouterDeps {
  botUserId: string;
  commandPrefix: string;
  faucetCurrencyCode: string;
  faucetCooldownHours: number;
  faucetDailyAmount: number;
  faucetMinXrpBalance: number;
  tokenIssuer: string;
  faucetWalletSeed: string;
  sendMessage: (roomId: string, body: string) => Promise<void>;
  sendTyping?: (roomId: string, typing: boolean) => Promise<void>;
  resolveDmRoom?: (sender: string) => Promise<string>;
  resolveRoomMemberCount?: (roomId: string) => Promise<number>;
  faucetStore: FaucetStore;
  xrpl: XrplService;
}

export class CommandRouter {
  private readonly deps: CommandRouterDeps;
  private readonly handlers = new Map<string, CommandHandler>();
  private readonly sensitiveCommands = new Set([
    "balance",
    "tokens",
    "whoami",
    "history",
    "trust",
    "trustdebug",
    "lp",
    "faucet",
    "reminders",
  ]);

  constructor(deps: CommandRouterDeps) {
    this.deps = deps;
    this.registerDefaults();
  }

  private register(name: string, handler: CommandHandler): void {
    this.handlers.set(name, handler);
  }

  async handleMessage(roomId: string, event: MatrixMessageEvent): Promise<void> {
    if (!event.content?.body || event.sender === this.deps.botUserId) return;

    const body = event.content.body.trim();
    if (!body.startsWith(this.deps.commandPrefix)) return;

    const raw = body.slice(this.deps.commandPrefix.length);
    const [command, ...rest] = raw.split(/\s+/);
    const commandKey = command.toLowerCase();
    const handler = this.handlers.get(commandKey);
    if (!handler) return;

    let replyRoomId = roomId;
    if (this.sensitiveCommands.has(commandKey) && this.deps.resolveDmRoom && this.deps.resolveRoomMemberCount) {
      const memberCount = await this.deps.resolveRoomMemberCount(roomId);
      if (memberCount > 2) {
        replyRoomId = await this.deps.resolveDmRoom(event.sender);
        await this.deps.sendMessage(
          roomId,
          "I sent your response via DM to avoid sharing wallet details in a group room.",
        );
      }
    }

    const context: CommandContext = {
      roomId,
      sender: event.sender,
      args: rest.join(" ").trim(),
      replyRoomId,
    };
    await handler(context);
  }

  private registerDefaults(): void {
    this.register("help", async ({ replyRoomId }) => {
      const p = this.deps.commandPrefix;
      await this.deps.sendMessage(
        replyRoomId,
        [
          "**TextRP Bot Commands**",
          `${p}help - Show commands`,
          `${p}ping - Bot health check`,
          `${p}whoami - Show your Matrix ID and wallet`,
          `${p}balance - XRP and faucet token balance`,
          `${p}tokens - Non-zero trustline balances`,
          `${p}faucet - Claim daily faucet payout`,
          `${p}trust - Check trustline status`,
          `${p}trustdebug - Dump trustline details`,
          `${p}lp - LP NFT multiplier status`,
          `${p}history - Faucet claim history`,
          `${p}reminders [status|on|off|set <hours>]`,
        ].join("\n"),
      );
    });

    this.register("ping", async ({ replyRoomId }) => {
      await this.deps.sendMessage(replyRoomId, "Pong. Appservice is online.");
    });

    this.register("whoami", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      await this.deps.sendMessage(
        replyRoomId,
        `TextRP ID: \`${sender}\`\nWallet: \`${wallet ?? "Not detected"}\``,
      );
    });

    this.register("balance", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      if (!this.deps.xrpl.isValidAddress(wallet)) {
        await this.deps.sendMessage(replyRoomId, `Invalid XRP address: \`${wallet}\``);
        return;
      }

      await this.deps.sendTyping?.(replyRoomId, true);
      const xrpBalance = await this.deps.xrpl.getAccountBalance(wallet);
      const trustLine = await this.deps.xrpl.checkTrustLine(wallet, this.deps.faucetCurrencyCode, this.deps.tokenIssuer);
      await this.deps.sendTyping?.(replyRoomId, false);

      if (xrpBalance == null) {
        await this.deps.sendMessage(replyRoomId, "Account not found or unavailable on XRPL.");
        return;
      }

      const tokenLine = trustLine
        ? `${this.deps.faucetCurrencyCode} Balance: ${trustLine.balance}`
        : `${this.deps.faucetCurrencyCode} trustline missing`;
      await this.deps.sendMessage(replyRoomId, `XRP Balance: ${xrpBalance.toFixed(6)}\n${tokenLine}\nAddress: \`${wallet}\``);
    });

    this.register("tokens", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const tokens = await this.deps.xrpl.getTokenBalances(wallet);
      if (tokens == null) {
        await this.deps.sendMessage(replyRoomId, "Could not fetch token balances right now.");
        return;
      }
      if (tokens.length === 0) {
        await this.deps.sendMessage(replyRoomId, "No non-zero token balances found.");
        return;
      }
      const lines = tokens.map((token) => `${token.currency}: ${token.balance}`);
      await this.deps.sendMessage(replyRoomId, `Token balances for \`${wallet}\`:\n${lines.join("\n")}`);
    });

    this.register("trust", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const trustLine = await this.deps.xrpl.checkTrustLine(wallet, this.deps.faucetCurrencyCode, this.deps.tokenIssuer);
      if (!trustLine) {
        await this.deps.sendMessage(
          replyRoomId,
          `No trust line found.\nCurrency: ${this.deps.faucetCurrencyCode}\nIssuer: \`${this.deps.tokenIssuer}\``,
        );
        return;
      }
      await this.deps.sendMessage(
        replyRoomId,
        `Trust line found.\nBalance: ${trustLine.balance}\nLimit: ${trustLine.limit}`,
      );
    });

    this.register("trustdebug", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const tokens = await this.deps.xrpl.getTokenBalances(wallet);
      if (tokens == null) {
        await this.deps.sendMessage(replyRoomId, "Unable to inspect trust lines right now.");
        return;
      }
      const details = tokens.slice(0, 10).map((token, i) => `${i + 1}. ${token.currency} ${token.balance} issuer=${token.issuer}`);
      await this.deps.sendMessage(replyRoomId, details.length > 0 ? details.join("\n") : "No trust lines found.");
    });

    this.register("lp", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const configured = new Set(this.deps.xrpl.getLpNfts().map(([issuer, taxon]) => `${issuer}:${taxon}`));
      if (configured.size === 0) {
        await this.deps.sendMessage(replyRoomId, "LP_INFO is not configured.");
        return;
      }
      const nfts = await this.deps.xrpl.getAccountNfts(wallet);
      if (nfts == null) {
        await this.deps.sendMessage(replyRoomId, "Could not fetch NFT data.");
        return;
      }

      let nftCount = 0;
      for (const nft of nfts) {
        const key = `${String(nft.Issuer ?? nft.issuer)}:${Number(nft.NFTokenTaxon ?? nft.nft_taxon)}`;
        if (configured.has(key)) nftCount += 1;
      }

      const multiplier = nftCount <= 0 ? 1 : nftCount === 1 ? 1.5 : nftCount;
      await this.deps.sendMessage(replyRoomId, `Matching LP NFTs: ${nftCount}\nFaucet multiplier: ${multiplier}x`);
    });

    this.register("history", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const history = await this.deps.faucetStore.getUserClaimHistory(wallet);
      if (history.length === 0) {
        await this.deps.sendMessage(replyRoomId, "No faucet claim history found.");
        return;
      }
      const row = history[0];
      await this.deps.sendMessage(
        replyRoomId,
        `Total claims: ${row.claim_count}\nTotal claimed: ${row.total_claimed} ${this.deps.faucetCurrencyCode}\nLast tx: ${shortHash(
          String(row.last_tx_hash ?? ""),
        )}`,
      );
    });

    this.register("reminders", async ({ sender, args, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      const normalized = args.trim().toLowerCase();
      if (!normalized || normalized === "status") {
        const prefs = await this.deps.faucetStore.getUserPreferences(wallet);
        if (!prefs) {
          await this.deps.sendMessage(replyRoomId, "Reminders are enabled with a 1 hour offset.");
          return;
        }
        await this.deps.sendMessage(
          replyRoomId,
          `Reminders: ${prefs.reminders_enabled ? "enabled" : "disabled"}\nOffset: ${prefs.reminder_offset} hour(s)`,
        );
        return;
      }
      if (normalized === "on") {
        await this.deps.faucetStore.setUserPreferences(wallet, { reminders_enabled: true });
        await this.deps.sendMessage(replyRoomId, "Reminders enabled.");
        return;
      }
      if (normalized === "off") {
        await this.deps.faucetStore.setUserPreferences(wallet, { reminders_enabled: false });
        await this.deps.sendMessage(replyRoomId, "Reminders disabled.");
        return;
      }
      if (normalized.startsWith("set ")) {
        const offset = Number.parseInt(normalized.split(/\s+/)[1] ?? "", 10);
        if (Number.isFinite(offset) && offset >= 0 && offset <= 24) {
          await this.deps.faucetStore.setUserPreferences(wallet, { reminder_offset: offset });
          await this.deps.sendMessage(replyRoomId, `Reminder offset set to ${offset} hour(s).`);
          return;
        }
      }
      await this.deps.sendMessage(replyRoomId, `Usage: ${this.deps.commandPrefix}reminders [on|off|set <hours>|status]`);
    });

    this.register("faucet", async ({ sender, replyRoomId }) => {
      const wallet = extractWalletFromUserId(sender);
      if (!wallet) {
        await this.deps.sendMessage(replyRoomId, "Could not extract your XRPL wallet from your Matrix ID.");
        return;
      }
      if (!this.deps.faucetWalletSeed || !this.deps.tokenIssuer) {
        await this.deps.sendMessage(replyRoomId, "Faucet is not configured.");
        return;
      }

      const xrpBalance = await this.deps.xrpl.getAccountBalance(wallet);
      if (xrpBalance != null && xrpBalance < this.deps.faucetMinXrpBalance) {
        await this.deps.sendMessage(
          replyRoomId,
          `You need at least ${this.deps.faucetMinXrpBalance} XRP before using the faucet.`,
        );
        return;
      }

      const trustLine = await this.deps.xrpl.checkTrustLine(wallet, this.deps.faucetCurrencyCode, this.deps.tokenIssuer);
      if (!trustLine) {
        await this.deps.sendMessage(replyRoomId, "Trust line required before claiming faucet tokens.");
        return;
      }

      const eligibility = await this.deps.faucetStore.checkClaimEligibility(wallet);
      if (!eligibility.eligible) {
        await this.deps.sendMessage(replyRoomId, `Cannot claim right now: ${eligibility.reason}`);
        return;
      }

      let baseAmount = this.deps.faucetDailyAmount;
      const faucetTrust = await this.deps.xrpl.checkTrustLine(
        xrplWalletFromSeed(this.deps.faucetWalletSeed),
        this.deps.faucetCurrencyCode,
        this.deps.tokenIssuer,
      );
      if (faucetTrust) {
        const computed = Math.floor(Number.parseFloat(faucetTrust.balance) * FAUCET_BALANCE_FACTOR);
        if (computed > 0) baseAmount = computed;
      }

      const nfts = await this.deps.xrpl.getAccountNfts(wallet);
      const configured = new Set(this.deps.xrpl.getLpNfts().map(([issuer, taxon]) => `${issuer}:${taxon}`));
      let nftCount = 0;
      if (nfts && configured.size > 0) {
        for (const nft of nfts) {
          const key = `${String(nft.Issuer ?? nft.issuer)}:${Number(nft.NFTokenTaxon ?? nft.nft_taxon)}`;
          if (configured.has(key)) nftCount += 1;
        }
      }
      const multiplier = nftCount <= 0 ? 1 : nftCount === 1 ? 1.5 : nftCount;
      const finalAmount = Math.max(1, Math.floor(baseAmount * multiplier));

      const txResult = await this.deps.xrpl.sendIssuedCurrencyPayment({
        walletSeed: this.deps.faucetWalletSeed,
        toAddress: wallet,
        amount: String(finalAmount),
        currency: this.deps.faucetCurrencyCode,
        issuer: this.deps.tokenIssuer,
        memo: `Daily faucet claim`,
      });

      if (!txResult.success || !txResult.txHash) {
        await this.deps.sendMessage(replyRoomId, `Faucet payment failed: ${txResult.error ?? "Unknown error"}`);
        return;
      }

      await this.deps.faucetStore.recordClaim(wallet, String(finalAmount), txResult.txHash);
      const userPrefs = (await this.deps.faucetStore.getUserPreferences(wallet)) as
        | { reminders_enabled?: boolean; reminder_offset?: number }
        | null;
      if (!userPrefs || userPrefs.reminders_enabled !== false) {
        const offset = Number(userPrefs?.reminder_offset ?? 1);
        const reminderSeconds = Math.max(this.deps.faucetCooldownHours - offset, 0) * 3600;
        await this.deps.faucetStore.scheduleReminder(
          wallet,
          replyRoomId,
          Math.trunc(Date.now() / 1000) + reminderSeconds,
          `Your ${this.deps.faucetCurrencyCode} claim window is open. Use ${this.deps.commandPrefix}faucet.`,
        );
      }

      await this.deps.sendMessage(
        replyRoomId,
        [
          `Faucet claim successful.`,
          `Payout: ${finalAmount} ${this.deps.faucetCurrencyCode}`,
          `Base: ${baseAmount}`,
          `LP multiplier: ${multiplier}x`,
          `Transaction: ${shortHash(txResult.txHash)}`,
          txResult.explorerUrl ? `Explorer: ${txResult.explorerUrl}` : "",
        ]
          .filter(Boolean)
          .join("\n"),
      );
    });
  }
}

function xrplWalletFromSeed(seed: string): string {
  try {
    const wallet = xrpl.Wallet.fromSeed(seed);
    return wallet.classicAddress;
  } catch {
    return "";
  }
}

