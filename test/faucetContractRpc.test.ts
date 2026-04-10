import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { afterEach, describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { faucet_contract: FaucetContract } = require("../faucet_contract/src/faucet_contract.js") as {
  faucet_contract: new (config?: { cooldownHours?: number; dbFile?: string }) => {
    sendOutput: (user: unknown, output: unknown) => Promise<void>;
    handleRequest: (
      user: { send: (output: unknown) => Promise<void> },
      message: Record<string, unknown>,
      context: { isReadOnly: boolean; epoch?: number },
    ) => Promise<void>;
  };
};

const cleanupPaths: string[] = [];

afterEach(() => {
  while (cleanupPaths.length > 0) {
    const file = cleanupPaths.pop();
    if (file && fs.existsSync(file)) {
      fs.rmSync(file, { force: true });
    }
  }
});

describe("faucet contract rpc", () => {
  it("rejects write commands in readonly mode", async () => {
    const dbFile = path.join(os.tmpdir(), `hp-contract-${Date.now()}-1.db`);
    cleanupPaths.push(dbFile);

    const app = new FaucetContract({ dbFile, cooldownHours: 24 });
    const outputs: Array<Record<string, unknown>> = [];
    const user = {
      send: async (output: unknown) => {
        outputs.push(output as Record<string, unknown>);
      },
    };
    app.sendOutput = async (u, output) => {
      await (u as typeof user).send(output);
    };

    await app.handleRequest(
      user,
      { v: 1, id: "req-1", cmd: "claim.record", wallet: "rWallet", amount: "1", tx_hash: "TX1" },
      { isReadOnly: true, epoch: 1700000000 },
    );

    expect(outputs).toHaveLength(1);
    expect(outputs[0].ok).toBe(false);
    expect((outputs[0].error as { code?: string })?.code).toBe("READONLY_WRITE");
  });

  it("uses context epoch for claim timestamps", async () => {
    const dbFile = path.join(os.tmpdir(), `hp-contract-${Date.now()}-2.db`);
    cleanupPaths.push(dbFile);

    const app = new FaucetContract({ dbFile, cooldownHours: 24 });
    const outputs: Array<Record<string, unknown>> = [];
    const user = {
      send: async (output: unknown) => {
        outputs.push(output as Record<string, unknown>);
      },
    };
    app.sendOutput = async (u, output) => {
      await (u as typeof user).send(output);
    };

    const recordEpoch = 1_700_000_123;
    await app.handleRequest(
      user,
      { v: 1, id: "req-2", cmd: "claim.record", wallet: "rWallet", amount: "10", tx_hash: "TX2" },
      { isReadOnly: false, epoch: recordEpoch },
    );

    await app.handleRequest(user, { v: 1, id: "req-3", cmd: "claim.history", wallet: "rWallet" }, { isReadOnly: true, epoch: 1_700_000_130 });

    const historyResponse = outputs.find((output) => output.id === "req-3");
    const history = (historyResponse?.data as { history?: Array<Record<string, unknown>> } | undefined)?.history ?? [];
    expect(history).toHaveLength(1);
    expect(history[0].first_claim).toBe(new Date(recordEpoch * 1000).toISOString().replace("Z", ""));
  });

  it("uses unix epoch fallback when readonly context epoch is missing", async () => {
    const dbFile = path.join(os.tmpdir(), `hp-contract-${Date.now()}-3.db`);
    cleanupPaths.push(dbFile);

    const app = new FaucetContract({ dbFile, cooldownHours: 24 });
    const outputs: Array<Record<string, unknown>> = [];
    const user = {
      send: async (output: unknown) => {
        outputs.push(output as Record<string, unknown>);
      },
    };
    app.sendOutput = async (u, output) => {
      await (u as typeof user).send(output);
    };

    const nowEpoch = Math.trunc(Date.now() / 1000);
    await app.handleRequest(
      user,
      { v: 1, id: "req-4", cmd: "claim.record", wallet: "rWallet", amount: "10", tx_hash: "TX3" },
      { isReadOnly: false, epoch: nowEpoch },
    );

    await app.handleRequest(
      user,
      { v: 1, id: "req-5", cmd: "claim.eligibility", wallet: "rWallet" },
      { isReadOnly: true },
    );

    const eligibilityResponse = outputs.find((output) => output.id === "req-5");
    const data = (eligibilityResponse?.data as { eligible?: boolean; reason?: string; seconds_remaining?: number } | undefined) ?? {};
    expect(data.eligible).toBe(false);
    expect(typeof data.seconds_remaining).toBe("number");
    expect((data.seconds_remaining ?? 0) > 0).toBe(true);
    expect(data.reason).toBeUndefined();
  });
});
