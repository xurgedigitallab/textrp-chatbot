import "dotenv/config";
import process from "node:process";

import { AppserviceBot } from "./bot/appserviceBot.js";
import { loadConfig, validateConfig } from "./config.js";

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
  let stopping = false;
  const shutdown = async (): Promise<void> => {
    if (stopping) return;
    stopping = true;
    try {
      await bot.stop();
    } finally {
      process.exit(0);
    }
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  await bot.start();
  console.log(
    `TextRP appservice started on ${config.matrixAsHost}:${config.matrixAsPort} for ${config.textrpUsername}`,
  );
}

main().catch((error) => {
  console.error("Fatal startup error:", error);
  process.exit(1);
});

