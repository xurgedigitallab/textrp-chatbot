import { describe, expect, it } from "vitest";

import { loadConfig, validateConfig } from "../src/config.js";

describe("config", () => {
  it("loads hp-state faucet path semantics", () => {
    const cfg = loadConfig({
      HP_STATE_DIR: "/hp/state",
      FAUCET_DB_PATH: "faucet.db",
    } as NodeJS.ProcessEnv);
    expect(cfg.faucetDbPath).toBe("/hp/state/faucet.db");
  });

  it("flags missing required appservice variables", () => {
    const cfg = loadConfig({ TEXTRP_USERNAME: "@bot:example.org" } as NodeJS.ProcessEnv);
    const validation = validateConfig(cfg);
    expect(validation.ok).toBe(false);
    if (!validation.ok) {
      expect(validation.errors.length).toBeGreaterThan(0);
    }
  });
});

