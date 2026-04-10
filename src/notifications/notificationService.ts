import type { FaucetStore } from "../services/faucetStore.js";
import { InAppNotificationStore } from "../storage/inAppNotificationStore.js";

export type ReminderChannel = "matrix_dm" | "in_app";

export class NotificationService {
  constructor(
    private readonly faucetStore: FaucetStore,
    private readonly inAppStore: InAppNotificationStore,
  ) {}

  async notifyClaimSuccess(input: { wallet: string; amount: number; txHash: string }): Promise<void> {
    this.inAppStore.createNotification({
      wallet: input.wallet,
      type: "claim_success",
      title: "Faucet claim successful",
      message: `Payout ${input.amount} sent. Tx ${input.txHash.slice(0, 12)}...`,
    });
  }

  async scheduleClaimWindowReminder(input: {
    wallet: string;
    roomId?: string;
    reminderEpoch: number;
    currencyCode: string;
    commandPrefix: string;
    channels: ReminderChannel[];
  }): Promise<void> {
    const channels = new Set(input.channels);
    if (channels.has("matrix_dm") && input.roomId) {
      await this.faucetStore.scheduleReminder(
        input.wallet,
        input.roomId,
        input.reminderEpoch,
        `Your ${input.currencyCode} claim window is open. Use ${input.commandPrefix}faucet.`,
      );
    }
    if (channels.has("in_app")) {
      this.inAppStore.createNotification({
        wallet: input.wallet,
        type: "claim_window_open",
        title: "Claim window open",
        message: `Your ${input.currencyCode} faucet claim is available.`,
        deliverEpoch: input.reminderEpoch,
      });
    }
  }

  async listNotifications(wallet: string): Promise<Array<Record<string, unknown>>> {
    const rows = this.inAppStore.listVisible(wallet);
    return rows.map((row) => ({
      id: row.id,
      type: row.type,
      title: row.title,
      message: row.message,
      created_epoch: row.created_epoch,
      read: row.read_epoch > 0,
      read_epoch: row.read_epoch > 0 ? row.read_epoch : null,
    }));
  }

  async markNotificationsRead(wallet: string, ids: number[] | "all"): Promise<number> {
    return this.inAppStore.markRead(wallet, ids);
  }
}
