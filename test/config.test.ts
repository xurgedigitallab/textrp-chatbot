import { describe, expect, it } from "vitest";

import { loadConfig, validateConfig } from "../src/config.js";

describe("config", () => {
  it("loads contract server settings", () => {
    const cfg = loadConfig({
      HP_CONTRACT_SERVERS: "wss://a.example,wss://b.example",
      HP_CONTRACT_TIMEOUT_MS: "25000",
    } as NodeJS.ProcessEnv);
    expect(cfg.hpContractServers).toEqual(["wss://a.example", "wss://b.example"]);
    expect(cfg.hpContractTimeoutMs).toBe(25000);
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

