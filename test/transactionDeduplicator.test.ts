import { describe, expect, it } from "vitest";

import { TransactionDeduplicator } from "../src/bot/transactionDeduplicator.js";

describe("transaction deduplicator", () => {
  it("rejects duplicate transaction IDs", () => {
    const deduper = new TransactionDeduplicator();
    expect(deduper.isDuplicate("txn-1")).toBe(false);
    expect(deduper.isDuplicate("txn-1")).toBe(true);
  });

  it("evicts old IDs beyond capacity", () => {
    const deduper = new TransactionDeduplicator(2);
    expect(deduper.isDuplicate("txn-1")).toBe(false);
    expect(deduper.isDuplicate("txn-2")).toBe(false);
    expect(deduper.isDuplicate("txn-3")).toBe(false);
    expect(deduper.isDuplicate("txn-1")).toBe(false);
  });
});

