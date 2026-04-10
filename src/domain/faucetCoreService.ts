import * as xrpl from "xrpl";

import type { FaucetStateStore } from "../services/faucetStateStore.js";
import { FAUCET_BALANCE_FACTOR, type XrplService } from "../services/xrplClient.js";
import type { NotificationService, ReminderChannel } from "../notifications/notificationService.js";

export interface FaucetCoreConfig {
  faucetCurrencyCode: string;
  faucetCooldownHours: number;
  faucetDailyAmount: number;
  faucetMinXrpBalance: number;
  tokenIssuer: string;
  faucetWalletSeed: string;
  commandPrefix: string;
}

export interface ClaimStatus {
  eligible: boolean;
  reason?: string;
  secondsRemaining?: number;
  xrpBalance?: number | null;
  trustLinePresent: boolean;
  nextClaimEpoch?: number;
  cooldownHours: number;
}

export interface RedeemClaimParams {
  wallet: string;
  matrixRoomId?: string;
  reminderChannels?: ReminderChannel[];
  idempotencyKey?: string;
}

export interface RedeemClaimResult {
  success: boolean;
  reason?: string;
  payoutAmount?: number;
  baseAmount?: number;
  multiplier?: number;
  txHash?: string;
  explorerUrl?: string;
  reminderEpoch?: number;
}

export class FaucetCoreService {
  constructor(
    private readonly config: FaucetCoreConfig,
    private readonly faucetStore: FaucetStateStore,
    private readonly xrplService: XrplService,
    private readonly notificationService?: NotificationService,
  ) {}

  async getClaimStatus(wallet: string): Promise<ClaimStatus> {
    const xrpBalance = await this.xrplService.getAccountBalance(wallet);
    if (xrpBalance != null && xrpBalance < this.config.faucetMinXrpBalance) {
      return {
        eligible: false,
        reason: `Minimum XRP balance is ${this.config.faucetMinXrpBalance}`,
        xrpBalance,
        trustLinePresent: false,
        cooldownHours: this.config.faucetCooldownHours,
      };
    }

    const trustLine = await this.xrplService.checkTrustLine(
      wallet,
      this.config.faucetCurrencyCode,
      this.config.tokenIssuer,
    );
    if (!trustLine) {
      return {
        eligible: false,
        reason: "Trust line required before claiming faucet tokens",
        xrpBalance,
        trustLinePresent: false,
        cooldownHours: this.config.faucetCooldownHours,
      };
    }

    const eligibility = await this.faucetStore.checkClaimEligibility(wallet);
    const snapshotReader = this.faucetStore as FaucetStateStore & {
      getClaimSnapshot?: (wallet: string) => Promise<{ last_claim_epoch: number } | null>;
    };
    const snapshot = snapshotReader.getClaimSnapshot ? await snapshotReader.getClaimSnapshot(wallet) : null;
    const nextClaimEpoch =
      snapshot == null
        ? undefined
        : snapshot.last_claim_epoch + Math.max(this.config.faucetCooldownHours, 0) * 3600;

    return {
      eligible: eligibility.eligible,
      reason: eligibility.eligible
        ? undefined
        : formatCooldownReason(eligibility.secondsRemaining, eligibility.reason, this.config.faucetCooldownHours),
      secondsRemaining: eligibility.eligible ? undefined : eligibility.secondsRemaining,
      xrpBalance,
      trustLinePresent: true,
      nextClaimEpoch,
      cooldownHours: this.config.faucetCooldownHours,
    };
  }

  async getClaimHistory(wallet: string): Promise<Array<Record<string, unknown>>> {
    return this.faucetStore.getUserClaimHistory(wallet);
  }

  async setReminderPreferences(
    wallet: string,
    patch: { reminders_enabled?: boolean; reminder_offset?: number },
  ): Promise<boolean> {
    return this.faucetStore.setUserPreferences(wallet, patch as never);
  }

  async getReminderPreferences(wallet: string): Promise<Record<string, unknown> | null> {
    return this.faucetStore.getUserPreferences(wallet);
  }

  async redeemClaim(params: RedeemClaimParams): Promise<RedeemClaimResult> {
    if (!this.config.faucetWalletSeed || !this.config.tokenIssuer) {
      return { success: false, reason: "Faucet is not configured" };
    }

    const status = await this.getClaimStatus(params.wallet);
    if (!status.eligible) {
      return {
        success: false,
        reason: status.reason ?? "Not eligible",
      };
    }

    let baseAmount = this.config.faucetDailyAmount;
    const faucetTrust = await this.xrplService.checkTrustLine(
      xrplWalletFromSeed(this.config.faucetWalletSeed),
      this.config.faucetCurrencyCode,
      this.config.tokenIssuer,
    );
    if (faucetTrust) {
      const computed = Math.floor(Number.parseFloat(faucetTrust.balance) * FAUCET_BALANCE_FACTOR);
      if (computed > 0) baseAmount = computed;
    }

    const nfts = await this.xrplService.getAccountNfts(params.wallet);
    const configured = new Set(this.xrplService.getLpNfts().map(([issuer, taxon]) => `${issuer}:${taxon}`));
    let nftCount = 0;
    if (nfts && configured.size > 0) {
      for (const nft of nfts) {
        const key = `${String(nft.Issuer ?? nft.issuer)}:${Number(nft.NFTokenTaxon ?? nft.nft_taxon)}`;
        if (configured.has(key)) nftCount += 1;
      }
    }

    const multiplier = nftCount <= 0 ? 1 : nftCount === 1 ? 1.5 : nftCount;
    const finalAmount = Math.max(1, Math.floor(baseAmount * multiplier));

    const txResult = await this.xrplService.sendIssuedCurrencyPayment({
      walletSeed: this.config.faucetWalletSeed,
      toAddress: params.wallet,
      amount: String(finalAmount),
      currency: this.config.faucetCurrencyCode,
      issuer: this.config.tokenIssuer,
      memo: "Daily faucet claim",
    });

    if (!txResult.success || !txResult.txHash) {
      return { success: false, reason: txResult.error ?? "Payment failed" };
    }

    await this.faucetStore.recordClaim(params.wallet, String(finalAmount), txResult.txHash);
    const prefs = (await this.faucetStore.getUserPreferences(params.wallet)) as
      | { reminders_enabled?: boolean; reminder_offset?: number }
      | null;

    let reminderEpoch: number | undefined;
    if (!prefs || prefs.reminders_enabled !== false) {
      const offset = Number(prefs?.reminder_offset ?? 1);
      const reminderSeconds = Math.max(this.config.faucetCooldownHours - offset, 0) * 3600;
      reminderEpoch = Math.trunc(Date.now() / 1000) + reminderSeconds;
      await this.notificationService?.scheduleClaimWindowReminder({
        wallet: params.wallet,
        roomId: params.matrixRoomId,
        reminderEpoch,
        currencyCode: this.config.faucetCurrencyCode,
        commandPrefix: this.config.commandPrefix,
        channels: params.reminderChannels ?? ["matrix_dm"],
      });
      await this.notificationService?.notifyClaimSuccess({
        wallet: params.wallet,
        amount: finalAmount,
        txHash: txResult.txHash,
      });
    }

    return {
      success: true,
      payoutAmount: finalAmount,
      baseAmount,
      multiplier,
      txHash: txResult.txHash,
      explorerUrl: txResult.explorerUrl,
      reminderEpoch,
    };
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

function formatCooldownReason(
  secondsRemaining: number | undefined,
  reason: string | undefined,
  maxCooldownHours = 24,
): string | undefined {
  if (typeof secondsRemaining === "number" && Number.isFinite(secondsRemaining)) {
    const maxSeconds = Math.max(1, maxCooldownHours) * 3600;
    return `Please wait ${formatDuration(Math.min(Math.max(0, Math.ceil(secondsRemaining)), maxSeconds))} before claiming again`;
  }
  return toHumanCooldownReason(reason, maxCooldownHours);
}

function toHumanCooldownReason(reason: string | undefined, maxCooldownHours = 24): string | undefined {
  if (!reason) return reason;
  const waitPattern = /please wait\s+([\d.]+)\s+(seconds?|minutes?|hours?|days?)\b/i;
  const match = reason.match(waitPattern);
  if (!match) return reason;

  const amount = Number.parseFloat(match[1] ?? "");
  const unit = (match[2] ?? "").toLowerCase();
  if (!Number.isFinite(amount) || amount <= 0) return reason;

  let totalSeconds = 0;
  if (unit.startsWith("second")) totalSeconds = amount;
  else if (unit.startsWith("minute")) totalSeconds = amount * 60;
  else if (unit.startsWith("hour")) {
    // Guard for backends that accidentally label seconds as "hours".
    totalSeconds = amount > 1_000 ? amount : amount * 3600;
  } else if (unit.startsWith("day")) totalSeconds = amount * 86_400;

  if (totalSeconds <= 0) return reason;
  const maxSeconds = Math.max(1, maxCooldownHours) * 3600;
  return `Please wait ${formatDuration(Math.min(Math.ceil(totalSeconds), maxSeconds))} before claiming again`;
}

function formatDuration(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const parts: string[] = [];

  if (days > 0) parts.push(`${days} day${days === 1 ? "" : "s"}`);
  if (hours > 0) parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  if (minutes > 0 && days === 0) parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  if (parts.length === 0) parts.push("under a minute");

  return parts.slice(0, 2).join(" ");
}
