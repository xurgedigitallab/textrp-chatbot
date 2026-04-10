import http from "node:http";

import type { BotConfig } from "../../config.js";
import type { FaucetCoreService } from "../../domain/faucetCoreService.js";
import type { NotificationService } from "../../notifications/notificationService.js";
import type { IdentityLinkStore } from "../../storage/identityLinkStore.js";
import type { RedeemRequestStore } from "../../storage/redeemRequestStore.js";
import type { SessionService, XAppSessionClaims } from "../auth/sessionService.js";

interface XAppServerDeps {
  config: BotConfig;
  sessionService: SessionService;
  faucetCore: FaucetCoreService;
  identityLinks: IdentityLinkStore;
  notifications: NotificationService;
  redeemRequestStore: RedeemRequestStore;
}

export class XAppServer {
  private server?: http.Server;

  constructor(private readonly deps: XAppServerDeps) {}

  async start(): Promise<void> {
    await new Promise<void>((resolve) => {
      this.server = http.createServer((req, res) => {
        void this.handleRequest(req, res);
      });
      this.server.listen(this.deps.config.xappPort, this.deps.config.xappHost, () => resolve());
    });
  }

  async stop(): Promise<void> {
    if (!this.server) return;
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }

  private async handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    try {
      if (req.method === "GET" && url.pathname === "/health") {
        return this.json(res, 200, { ok: true, service: "xapp-backend" });
      }
      if (req.method === "POST" && url.pathname === "/xapp/auth/ott") {
        const body = await readJson(req);
        const walletAddress = String(body.walletAddress ?? "");
        const result = this.deps.sessionService.exchangeOtt({
          ott: String(body.ott ?? ""),
          walletAddress,
          xamanAccount: String(body.xamanAccount ?? walletAddress),
          matrixUserId: body.matrixUserId ? String(body.matrixUserId) : undefined,
        });
        return this.json(res, 200, {
          session: { token: result.token, tokenType: "Bearer", expiresInSeconds: this.deps.config.xappSessionTtlSeconds },
          matrix: {
            homeserver: this.deps.config.textrpHomeserver,
            userId: result.link.matrix_user_id,
          },
          identity: result.link,
        });
      }

      const session = this.requireAuth(req);
      if (req.method === "GET" && url.pathname === "/me") {
        const link = this.deps.identityLinks.getByWallet(session.wallet);
        const prefs = await this.deps.faucetCore.getReminderPreferences(session.wallet);
        return this.json(res, 200, {
          wallet: session.wallet,
          matrix_user_id: session.matrix_user_id,
          xaman_account: session.xaman_account,
          linked_identity: link,
          reminder_preferences: prefs,
        });
      }
      if (req.method === "GET" && url.pathname === "/claims/status") {
        const status = await this.deps.faucetCore.getClaimStatus(session.wallet);
        return this.json(res, 200, status);
      }
      if (req.method === "GET" && url.pathname === "/claims/history") {
        const history = await this.deps.faucetCore.getClaimHistory(session.wallet);
        return this.json(res, 200, { items: history });
      }
      if (req.method === "POST" && url.pathname === "/claims/redeem") {
        const body = await readJson(req);
        const requestKey = String(
          req.headers["idempotency-key"] ?? body.requestKey ?? "",
        );
        if (!requestKey) {
          return this.json(res, 400, { error: "idempotency-key is required" });
        }
        const cached = this.deps.redeemRequestStore.get(session.wallet, requestKey);
        if (cached) return this.json(res, 200, { ...cached, idempotentReplay: true });

        const result = await this.deps.faucetCore.redeemClaim({
          wallet: session.wallet,
          reminderChannels: Array.isArray(body.reminderChannels)
            ? body.reminderChannels.filter((v: unknown) => v === "matrix_dm" || v === "in_app")
            : ["in_app"],
        });
        const payload = {
          success: result.success,
          reason: result.reason,
          payoutAmount: result.payoutAmount,
          txHash: result.txHash,
          explorerUrl: result.explorerUrl,
          reminderEpoch: result.reminderEpoch,
        };
        this.deps.redeemRequestStore.set(session.wallet, requestKey, payload);
        return this.json(res, result.success ? 200 : 400, payload);
      }
      if (req.method === "PATCH" && url.pathname === "/preferences/reminders") {
        const body = await readJson(req);
        const reminderOffset = body.reminder_offset;
        const reminderOffsetNumber = typeof reminderOffset === "number" ? reminderOffset : undefined;
        if (
          reminderOffsetNumber != null &&
          (!Number.isInteger(reminderOffsetNumber) || reminderOffsetNumber < 0 || reminderOffsetNumber > 24)
        ) {
          return this.json(res, 400, { error: "reminder_offset must be an integer in range 0..24" });
        }
        await this.deps.faucetCore.setReminderPreferences(session.wallet, {
          reminders_enabled: typeof body.reminders_enabled === "boolean" ? body.reminders_enabled : undefined,
          reminder_offset: reminderOffsetNumber,
        });
        const prefs = await this.deps.faucetCore.getReminderPreferences(session.wallet);
        return this.json(res, 200, { preferences: prefs });
      }
      if (req.method === "GET" && url.pathname === "/notifications") {
        const items = await this.deps.notifications.listNotifications(session.wallet);
        return this.json(res, 200, { items });
      }
      if (req.method === "POST" && url.pathname === "/notifications/read") {
        const body = await readJson(req);
        const ids = Array.isArray(body.ids)
          ? body.ids.map((item: unknown) => Number(item)).filter((item: number) => Number.isInteger(item) && item > 0)
          : "all";
        const marked = await this.deps.notifications.markNotificationsRead(session.wallet, ids);
        return this.json(res, 200, { marked });
      }
      return this.json(res, 404, { error: "Not found" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unhandled error";
      if (message.toLowerCase().includes("token")) return this.json(res, 401, { error: message });
      return this.json(res, 400, { error: message });
    }
  }

  private requireAuth(req: http.IncomingMessage): XAppSessionClaims {
    const header = String(req.headers.authorization ?? "");
    if (!header.startsWith("Bearer ")) throw new Error("Missing bearer token");
    const token = header.slice("Bearer ".length).trim();
    return this.deps.sessionService.verifyToken(token);
  }

  private json(res: http.ServerResponse, statusCode: number, payload: unknown): void {
    res.statusCode = statusCode;
    res.setHeader("content-type", "application/json; charset=utf-8");
    res.end(JSON.stringify(payload));
  }
}

async function readJson(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
  }
  if (chunks.length === 0) return {};
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  if (!raw) return {};
  return JSON.parse(raw) as Record<string, unknown>;
}
