export interface UserPreferencesPatch {
  reminders_enabled?: boolean;
  reminder_offset?: number;
  timezone?: string;
}

export interface FaucetStateStore {
  checkClaimEligibility(wallet: string): Promise<{ eligible: boolean; reason?: string }>;
  recordClaim(wallet: string, amount: string, txHash: string, eventEpoch?: number): Promise<boolean>;
  getUserClaimHistory(wallet: string): Promise<Array<Record<string, unknown>>>;
  recordRoomJoin(roomId: string, roomName?: string): Promise<boolean>;
  markWelcomeSent(roomId: string): Promise<boolean>;
  getUserPreferences(wallet: string): Promise<Record<string, unknown> | null>;
  setUserPreferences(wallet: string, patch: UserPreferencesPatch): Promise<boolean>;
  scheduleReminder(wallet: string, roomId: string, reminderTime: number, message: string): Promise<boolean>;
  getPendingReminders(beforeTime?: number): Promise<Array<Record<string, unknown>>>;
  markReminderSent(reminderId: number): Promise<boolean>;
}
