import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { FaucetStore } from "../src/services/faucetStore.js";

const cleanupPaths: string[] = [];

afterEach(() => {
  while (cleanupPaths.length > 0) {
    const dir = cleanupPaths.pop();
    if (dir && fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("faucet store", () => {
  it("enforces cooldown and records claims", async () => {
    let epoch = 1_700_000_000;
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "faucet-store-"));
    cleanupPaths.push(root);
    const dbPath = path.join(root, "faucet.db");

    const store = new FaucetStore({
      dbPath,
      cooldownHours: 24,
      epochProvider: async () => epoch,
    });

    const firstCheck = await store.checkClaimEligibility("rWalletA");
    expect(firstCheck.eligible).toBe(true);

    const recorded = await store.recordClaim("rWalletA", "100", "TX_A");
    expect(recorded).toBe(true);

    const secondCheck = await store.checkClaimEligibility("rWalletA");
    expect(secondCheck.eligible).toBe(false);
    expect(secondCheck.secondsRemaining).toBeGreaterThan(0);

    epoch += 24 * 3600 + 60;
    const thirdCheck = await store.checkClaimEligibility("rWalletA");
    expect(thirdCheck.eligible).toBe(true);
  });

  it("schedules and returns pending reminders", async () => {
    let epoch = 1_700_000_000;
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "faucet-reminders-"));
    cleanupPaths.push(root);
    const dbPath = path.join(root, "faucet.db");

    const store = new FaucetStore({
      dbPath,
      cooldownHours: 24,
      epochProvider: async () => epoch,
    });

    await store.scheduleReminder("rWalletA", "!room:test", epoch + 30, "Reminder");
    let reminders = await store.getPendingReminders();
    expect(reminders.length).toBe(0);

    epoch += 60;
    reminders = await store.getPendingReminders();
    expect(reminders.length).toBe(1);
    expect(reminders[0].message).toBe("Reminder");
  });
});

