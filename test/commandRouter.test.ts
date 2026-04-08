import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { CommandRouter } from "../src/bot/commandRouter.js";
import { FaucetStore } from "../src/services/faucetStore.js";

describe("command router", () => {
  it("routes simple commands", async () => {
    const messages: Array<{ roomId: string; body: string }> = [];
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "router-"));
    const faucetStore = new FaucetStore({
      dbPath: path.join(root, "faucet.db"),
      cooldownHours: 24,
      epochProvider: async () => 1_700_000_000,
    });

    const router = new CommandRouter({
      botUserId: "@bot:example.org",
      commandPrefix: "!",
      faucetCurrencyCode: "TXT",
      faucetCooldownHours: 24,
      faucetDailyAmount: 100,
      faucetMinXrpBalance: 0.1,
      tokenIssuer: "rIssuer",
      faucetWalletSeed: "",
      faucetStore,
      xrpl: {
        isValidAddress: () => true,
        getAccountBalance: async () => 2,
        checkTrustLine: async () => ({ balance: "1", limit: "1000" }),
        getTokenBalances: async () => [],
        getAccountNfts: async () => [],
        getLpNfts: () => [],
        sendIssuedCurrencyPayment: async () => ({ success: false, error: "disabled" }),
      } as any,
      sendMessage: async (roomId, body) => {
        messages.push({ roomId, body });
      },
      resolveRoomMemberCount: async () => 2,
      resolveDmRoom: async () => "!dm:example.org",
    });

    await router.handleMessage("!room:example.org", {
      sender: "@r9J6xYxH9Q7k1QfWnNwm9RzL4duMN:example.org",
      content: { msgtype: "m.text", body: "!ping" },
    });

    expect(messages).toHaveLength(1);
    expect(messages[0].body).toContain("Pong");
  });

  it("redirects sensitive commands to DM in group rooms", async () => {
    const messages: Array<{ roomId: string; body: string }> = [];
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "router-dm-"));
    const faucetStore = new FaucetStore({
      dbPath: path.join(root, "faucet.db"),
      cooldownHours: 24,
      epochProvider: async () => 1_700_000_000,
    });

    const router = new CommandRouter({
      botUserId: "@bot:example.org",
      commandPrefix: "!",
      faucetCurrencyCode: "TXT",
      faucetCooldownHours: 24,
      faucetDailyAmount: 100,
      faucetMinXrpBalance: 0.1,
      tokenIssuer: "rIssuer",
      faucetWalletSeed: "",
      faucetStore,
      xrpl: {
        isValidAddress: () => true,
        getAccountBalance: async () => 2,
        checkTrustLine: async () => ({ balance: "1", limit: "1000" }),
        getTokenBalances: async () => [],
        getAccountNfts: async () => [],
        getLpNfts: () => [],
        sendIssuedCurrencyPayment: async () => ({ success: false, error: "disabled" }),
      } as any,
      sendMessage: async (roomId, body) => {
        messages.push({ roomId, body });
      },
      resolveRoomMemberCount: async () => 5,
      resolveDmRoom: async () => "!dm:example.org",
    });

    await router.handleMessage("!group:example.org", {
      sender: "@r9J6xYxH9Q7k1QfWnNwm9RzL4duMN:example.org",
      content: { msgtype: "m.text", body: "!whoami" },
    });

    expect(messages.length).toBeGreaterThanOrEqual(2);
    expect(messages[0].roomId).toBe("!group:example.org");
    expect(messages[1].roomId).toBe("!dm:example.org");
  });
});

