import * as xrpl from "xrpl";

export const XRPL_UNIX_EPOCH_OFFSET = 946684800;
export const FAUCET_BALANCE_FACTOR = 0.000001;
const SECP256K1_ALGORITHM = ((xrpl as any).ECDSA?.secp256k1 ?? "ecdsa-secp256k1") as any;

type TrustLine = {
  currency: string;
  account: string;
  balance: string;
  limit_peer: string;
};

export class XrplService {
  private readonly network: string;
  private readonly rpcUrl: string;
  private readonly lpNfts: Array<[string, number]>;
  private client: xrpl.Client;

  constructor(config: { network: string; rpcUrl?: string; lpInfo?: string }) {
    this.network = config.network;
    this.rpcUrl = config.rpcUrl ?? this.defaultRpcUrl(config.network);
    this.client = new xrpl.Client(this.rpcUrl);
    this.lpNfts = this.parseLpInfo(config.lpInfo ?? "");
  }

  private defaultRpcUrl(network: string): string {
    switch (network) {
      case "testnet":
        return "wss://s.altnet.rippletest.net:51233";
      case "devnet":
        return "wss://s.devnet.rippletest.net:51233";
      default:
        return "wss://s1.ripple.com";
    }
  }

  private parseLpInfo(raw: string): Array<[string, number]> {
    if (!raw.trim()) return [];
    return raw
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => {
        const [issuer, taxon] = entry.split(":");
        return [issuer, Number.parseInt(taxon, 10)] as [string, number];
      })
      .filter(([issuer, taxon]) => Boolean(issuer) && Number.isFinite(taxon));
  }

  async connect(): Promise<void> {
    if (!this.client.isConnected()) {
      await this.client.connect();
    }
  }

  async disconnect(): Promise<void> {
    if (this.client.isConnected()) {
      await this.client.disconnect();
    }
  }

  getLpNfts(): Array<[string, number]> {
    return [...this.lpNfts];
  }

  isValidAddress(address: string): boolean {
    return xrpl.isValidClassicAddress(address);
  }

  async getLedgerInfo(ledgerIndex: string = "validated"): Promise<Record<string, unknown> | null> {
    await this.connect();
    try {
      const response = (await this.client.request({
        command: "ledger",
        ledger_index: ledgerIndex as any,
      } as any)) as any;
      const ledger = response.result?.ledger as Record<string, unknown> | undefined;
      return ledger ?? null;
    } catch {
      return null;
    }
  }

  async getAccountInfo(address: string): Promise<Record<string, unknown> | null> {
    await this.connect();
    try {
      const response = await this.client.request({
        command: "account_info",
        account: address,
        ledger_index: "validated",
      });
      return (response.result?.account_data as unknown as Record<string, unknown>) ?? null;
    } catch {
      return null;
    }
  }

  async getAccountBalance(address: string): Promise<number | null> {
    const account = await this.getAccountInfo(address);
    if (!account) return null;
    const drops = String(account.Balance ?? "0");
    const xrp = xrpl.dropsToXrp(drops as any);
    return Number.parseFloat(String(xrp));
  }

  async getTokenBalances(address: string): Promise<Array<Record<string, string>> | null> {
    await this.connect();
    try {
      const response = await this.client.request({
        command: "account_lines",
        account: address,
        ledger_index: "validated",
      });
      const lines = (response.result?.lines as TrustLine[] | undefined) ?? [];
      return lines
        .filter((line) => Number.parseFloat(line.balance) !== 0)
        .map((line) => ({
          currency: line.currency,
          issuer: line.account,
          balance: line.balance,
        }));
    } catch {
      return null;
    }
  }

  async checkTrustLine(address: string, currency: string, issuer: string): Promise<{ balance: string; limit: string } | null> {
    await this.connect();
    try {
      const response = await this.client.request({
        command: "account_lines",
        account: address,
        ledger_index: "validated",
      });
      const lines = (response.result?.lines as TrustLine[] | undefined) ?? [];
      const line = lines.find((item) => item.currency === currency && item.account === issuer);
      if (!line) return null;
      return {
        balance: line.balance,
        limit: line.limit_peer,
      };
    } catch {
      return null;
    }
  }

  async getAccountNfts(address: string, limit = 400): Promise<Array<Record<string, unknown>> | null> {
    await this.connect();
    try {
      const response = await this.client.request({
        command: "account_nfts",
        account: address,
        limit,
      });
      return (response.result?.account_nfts as unknown as Array<Record<string, unknown>> | undefined) ?? [];
    } catch {
      return null;
    }
  }

  async sendIssuedCurrencyPayment(params: {
    walletSeed: string;
    toAddress: string;
    amount: string;
    currency: string;
    issuer: string;
    memo?: string;
  }): Promise<{ success: boolean; txHash?: string; explorerUrl?: string; error?: string }> {
    await this.connect();
    try {
      const wallet = xrpl.Wallet.fromSeed(params.walletSeed, { algorithm: SECP256K1_ALGORITHM });
      const payment: xrpl.Payment = {
        TransactionType: "Payment",
        Account: wallet.classicAddress,
        Destination: params.toAddress,
        Amount: {
          currency: params.currency,
          issuer: params.issuer,
          value: params.amount,
        },
      };

      if (params.memo) {
        payment.Memos = [
          {
            Memo: {
              MemoData: Buffer.from(params.memo, "utf8").toString("hex").toUpperCase(),
            },
          },
        ];
      }

      const prepared = await this.client.autofill(payment);
      const signed = wallet.sign(prepared);
      const result = await this.client.submitAndWait(signed.tx_blob);
      const txHash = signed.hash;

      if (result.result.validated !== true) {
        return { success: false, error: "Transaction not validated" };
      }

      const explorerBase = this.network === "mainnet" ? "https://livenet.xrpl.org" : "https://testnet.xrpl.org";
      return {
        success: true,
        txHash,
        explorerUrl: `${explorerBase}/transactions/${txHash}`,
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown XRPL error",
      };
    }
  }
}

