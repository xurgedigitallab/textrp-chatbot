import "dotenv/config";
import process from "node:process";

import { AppserviceBot } from "./bot/appserviceBot.js";
import { loadConfig, validateConfig } from "./config.js";
import { SessionService } from "./xapp/auth/sessionService.js";
import { XAppServer } from "./xapp/api/xappServer.js";
import { RedeemRequestStore } from "./storage/redeemRequestStore.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const validation = validateConfig(config);
  if (!validation.ok) {
    for (const error of validation.errors) {
      console.error(error);
    }
    process.exit(1);
  }

  const bot = new AppserviceBot(config);
  const homeserverDomain = config.textrpUsername.split(":")[1] ?? "synapse.textrp.io";
  const redeemRequestStore = new RedeemRequestStore(config.xappStorageDir);
  const xappServer =
    config.xappEnabled
      ? new XAppServer({
          config,
          faucetCore: bot.getFaucetCoreService(),
          notifications: bot.getNotificationService(),
          identityLinks: bot.getIdentityLinkStore(),
          redeemRequestStore,
          sessionService: new SessionService(
            bot.getIdentityLinkStore(),
            config.xappSessionSecret,
            config.xappSessionTtlSeconds,
            config.xappJwtIssuer,
            config.xappJwtAudience,
            homeserverDomain,
          ),
        })
      : null;
  let stopping = false;
  const shutdown = async (): Promise<void> => {
    if (stopping) return;
    stopping = true;
    try {
      if (xappServer) {
        await xappServer.stop();
      }
      await bot.stop();
    } finally {
      process.exit(0);
    }
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  await bot.start();
  if (xappServer) {
    await xappServer.start();
    console.log(`xApp backend started on ${config.xappHost}:${config.xappPort}`);
  }
  console.log(
    `TextRP appservice started on ${config.matrixAsHost}:${config.matrixAsPort} for ${config.textrpUsername}`,
  );
}

main().catch((error) => {
  console.error("Fatal startup error:", error);
  process.exit(1);
});

