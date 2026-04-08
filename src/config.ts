import path from "node:path";

export interface BotConfig {
  textrpHomeserver: string;
  textrpUsername: string;
  textrpRoomId?: string;
  matrixAsToken: string;
  matrixHsToken: string;
  matrixAsUrl: string;
  matrixAsHost: string;
  matrixAsPort: number;
  matrixAsId: string;
  matrixAsSenderLocalpart: string;
  xrplNetwork: string;
  xrplRpcUrl?: string;
  faucetWalletSeed: string;
  faucetCurrencyCode: string;
  faucetDailyAmount: number;
  faucetCooldownHours: number;
  faucetMinXrpBalance: number;
  faucetColdWallet: string;
  tokenIssuer: string;
  faucetAdminUsers: string[];
  hpStateDir: string;
  faucetDbPath: string;
  commandPrefix: string;
  logLevel: string;
  invalidateTokenOnShutdown: boolean;
  lpInfo: string;
}

const REQUIRED_ENV = [
  "MATRIX_AS_TOKEN",
  "MATRIX_HS_TOKEN",
  "MATRIX_AS_URL",
  "MATRIX_AS_ID",
  "MATRIX_AS_SENDER_LOCALPART",
] as const;

const asBool = (value: string | undefined, fallback = false): boolean => {
  if (!value) return fallback;
  return value.toLowerCase() === "true";
};

const asInt = (value: string | undefined, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? fallback : parsed;
};

const asFloat = (value: string | undefined, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number.parseFloat(value);
  return Number.isNaN(parsed) ? fallback : parsed;
};

function resolveFaucetDbPath(rawPath: string, hpStateDir: string): string {
  if (path.isAbsolute(rawPath)) return rawPath;
  return path.join(hpStateDir, "faucet.db");
}

export function loadConfig(env = process.env): BotConfig {
  const hpStateDir = env.HP_STATE_DIR ?? "/hp/state";
  const faucetDbPath = resolveFaucetDbPath(env.FAUCET_DB_PATH ?? "faucet.db", hpStateDir);

  return {
    textrpHomeserver: env.TEXTRP_HOMESERVER ?? "https://synapse.textrp.io",
    textrpUsername: env.TEXTRP_USERNAME ?? "@yourbot:synapse.textrp.io",
    textrpRoomId: env.TEXTRP_ROOM_ID,
    matrixAsToken: env.MATRIX_AS_TOKEN ?? "",
    matrixHsToken: env.MATRIX_HS_TOKEN ?? "",
    matrixAsUrl: env.MATRIX_AS_URL ?? "",
    matrixAsHost: env.MATRIX_AS_HOST ?? "0.0.0.0",
    matrixAsPort: asInt(env.MATRIX_AS_PORT, 9009),
    matrixAsId: env.MATRIX_AS_ID ?? "",
    matrixAsSenderLocalpart: env.MATRIX_AS_SENDER_LOCALPART ?? "",
    xrplNetwork: env.XRPL_NETWORK ?? "mainnet",
    xrplRpcUrl: env.XRPL_RPC_URL,
    faucetWalletSeed: env.FAUCET_WALLET_SEED ?? env.FAUCET_HOT_WALLET_SEED ?? "",
    faucetCurrencyCode: env.FAUCET_CURRENCY_CODE ?? "TXT",
    faucetDailyAmount: asFloat(env.FAUCET_DAILY_AMOUNT, 100),
    faucetCooldownHours: asInt(env.FAUCET_COOLDOWN_HOURS ?? env.FAUCET_CLAIM_COOLDOWN_HOURS, 24),
    faucetMinXrpBalance: asFloat(env.FAUCET_MIN_XRP_BALANCE, 0.1),
    faucetColdWallet: env.FAUCET_COLD_WALLET ?? "",
    tokenIssuer: env.TOKEN_ISSUER ?? env.FAUCET_TOKEN_ISSUER ?? env.FAUCET_COLD_WALLET ?? "",
    faucetAdminUsers: (env.FAUCET_ADMIN_USERS ?? "")
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean),
    hpStateDir,
    faucetDbPath,
    commandPrefix: env.BOT_COMMAND_PREFIX ?? "!",
    logLevel: env.BOT_LOG_LEVEL ?? "info",
    invalidateTokenOnShutdown: asBool(env.INVALIDATE_TOKEN_ON_SHUTDOWN, false),
    lpInfo: env.LP_INFO ?? "",
  };
}

export function validateConfig(config: BotConfig): { ok: true } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  for (const key of REQUIRED_ENV) {
    const field = key
      .toLowerCase()
      .replace(/^matrix_/, "matrix")
      .replace(/_([a-z])/g, (_, c) => c.toUpperCase()) as keyof BotConfig;
    if (!config[field]) {
      errors.push(`${key} is required for appservice mode`);
    }
  }

  if (!config.textrpUsername.startsWith("@") || !config.textrpUsername.includes(":")) {
    errors.push("TEXTRP_USERNAME must be a full Matrix user ID, for example @bot:example.com");
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }
  return { ok: true };
}

