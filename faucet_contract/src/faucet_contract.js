const Database = require("better-sqlite3");

const dbFile = "faucet_data.db";
const RPC_VERSION = 1;

const WRITABLE_COMMANDS = new Set([
    "claim.record",
    "room.join",
    "room.welcome_sent",
    "prefs.set",
    "reminder.schedule",
    "reminder.mark_sent",
    "blacklist.set",
    "blacklist.remove",
]);

function toIso(epoch) {
    return new Date(Math.max(Number(epoch) || 0, 0) * 1000).toISOString().replace("Z", "");
}

function asEpoch(value) {
    if (value == null) return null;
    if (typeof value === "number") return Math.trunc(value);
    if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return Number.parseInt(value.trim(), 10);
    return null;
}

function parseNumber(value, fallback = 0) {
    const parsed = Number.parseFloat(String(value));
    return Number.isNaN(parsed) ? fallback : parsed;
}

function addAmounts(a, b) {
    return (parseNumber(a, 0) + parseNumber(b, 0)).toString();
}

class faucet_contract {
    sendOutput;

    constructor(config = {}) {
        this.cooldownHours = Number(config.cooldownHours ?? 24);
        this.db = new Database(config.dbFile ?? dbFile);
        this.db.exec(`
            CREATE TABLE IF NOT EXISTS kv_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        `);
        this.initializeDefaults();
    }

    initializeDefaults() {
        this.ensureValue("claims", {});
        this.ensureValue("blacklist", {});
        this.ensureValue("faucet_stats", {
            id: 1,
            total_claims: 0,
            total_distributed: "0",
            unique_wallets: 0,
            last_updated_epoch: 0,
        });
        this.ensureValue("room_joins", {});
        this.ensureValue("user_preferences", {});
        this.ensureValue("scheduled_reminders", []);
        this.ensureValue("next_reminder_id", 1);
    }

    ensureValue(key, fallback) {
        const existing = this.readValue(key);
        if (existing == null) this.writeValue(key, fallback);
    }

    readValue(key) {
        const row = this.db.prepare("SELECT value FROM kv_state WHERE key = ?").get(key);
        if (!row || typeof row.value !== "string") return null;
        try {
            return JSON.parse(row.value);
        } catch {
            return null;
        }
    }

    writeValue(key, value) {
        this.db
            .prepare(`
                INSERT INTO kv_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            `)
            .run(key, JSON.stringify(value));
    }

    response({ id, cmd, ok, data, error }) {
        const payload = { v: RPC_VERSION, id: id ?? null, ok: Boolean(ok), cmd };
        if (ok) payload.data = data ?? {};
        else payload.error = error ?? { code: "UNKNOWN", message: "Unknown contract error" };
        return payload;
    }

    epochFromContext(contextEpoch) {
        const n = Number(contextEpoch);
        if (!Number.isFinite(n) || n <= 0) return Math.trunc(Date.now() / 1000);
        if (n > 1_000_000_000_000) return Math.trunc(n / 1000);
        return Math.trunc(n);
    }

    async handleRequest(user, message, reqContext = {}) {
        const requestId = message?.id ?? null;
        const cmd = String(message?.cmd ?? message?.type ?? "");
        const isReadOnly = Boolean(reqContext.isReadOnly);
        const nowEpoch = this.epochFromContext(reqContext.epoch);

        if (!cmd) {
            await this.sendOutput(user, this.response({
                id: requestId,
                cmd: "unknown",
                ok: false,
                error: { code: "INVALID_COMMAND", message: "Request command is missing" },
            }));
            return;
        }

        if (isReadOnly && WRITABLE_COMMANDS.has(cmd)) {
            await this.sendOutput(user, this.response({
                id: requestId,
                cmd,
                ok: false,
                error: { code: "READONLY_WRITE", message: "Write command is not allowed in readonly mode" },
            }));
            return;
        }

        try {
            const data = await this.dispatch(cmd, message ?? {}, { nowEpoch });
            await this.sendOutput(user, this.response({ id: requestId, cmd, ok: true, data }));
        } catch (error) {
            await this.sendOutput(user, this.response({
                id: requestId,
                cmd,
                ok: false,
                error: {
                    code: "CONTRACT_ERROR",
                    message: error instanceof Error ? error.message : "Unhandled contract error",
                },
            }));
        }
    }

    async dispatch(cmd, request, runtime) {
        switch (cmd) {
            case "stat":
            case "ping":
                return { status: "Contract is online", epoch: runtime.nowEpoch };
            case "get":
                return { value: this.readValue("legacy_data") ?? "" };
            case "set":
                this.writeValue("legacy_data", String(request.data ?? ""));
                return { status: "success" };
            case "time.now":
                return { epoch: runtime.nowEpoch };
            case "claim.eligibility":
                return this.checkClaimEligibility(String(request.wallet ?? ""), runtime.nowEpoch);
            case "claim.record":
                return this.recordClaim({
                    wallet: String(request.wallet ?? ""),
                    amount: String(request.amount ?? "0"),
                    txHash: String(request.tx_hash ?? ""),
                    nowEpoch: runtime.nowEpoch,
                });
            case "claim.history":
                return this.getUserClaimHistory(String(request.wallet ?? ""));
            case "stats.get":
                return this.getStats();
            case "room.get":
                return this.getRoom(String(request.room_id ?? ""));
            case "room.join":
                return this.recordRoomJoin(String(request.room_id ?? ""), request.room_name, runtime.nowEpoch);
            case "room.welcome_sent":
                return this.markWelcomeSent(String(request.room_id ?? ""));
            case "prefs.get":
                return this.getUserPreferences(String(request.wallet ?? ""));
            case "prefs.set":
                return this.setUserPreferences(String(request.wallet ?? ""), request.patch ?? {}, runtime.nowEpoch);
            case "reminders.pending":
                return this.getPendingReminders(request.before_epoch ?? null, runtime.nowEpoch);
            case "reminder.schedule":
                return this.scheduleReminder(request, runtime.nowEpoch);
            case "reminder.mark_sent":
                return this.markReminderSent(Number(request.reminder_id ?? 0), runtime.nowEpoch);
            case "blacklist.set":
                return this.setBlacklist(request, runtime.nowEpoch);
            case "blacklist.remove":
                return this.removeBlacklist(String(request.wallet ?? ""));
            default:
                throw new Error(`Unknown command: ${cmd}`);
        }
    }

    checkClaimEligibility(wallet, nowEpoch) {
        if (!wallet) return { eligible: false, reason: "Wallet is required" };
        const blacklist = this.readValue("blacklist") ?? {};
        if (blacklist[wallet]) return { eligible: false, reason: "Wallet is blacklisted from faucet" };

        const claims = this.readValue("claims") ?? {};
        const claim = claims[wallet];
        if (!claim) return { eligible: true };

        const elapsed = nowEpoch - Number(claim.last_claim_epoch ?? 0);
        const cooldownSeconds = this.cooldownHours * 3600;
        if (elapsed < cooldownSeconds) {
            const secondsRemaining = Math.max(0, Math.trunc(cooldownSeconds - elapsed));
            return { eligible: false, seconds_remaining: secondsRemaining };
        }
        return { eligible: true };
    }

    recordClaim({ wallet, amount, txHash, nowEpoch }) {
        if (!wallet) throw new Error("wallet is required");
        if (!txHash) throw new Error("tx_hash is required");

        const claims = this.readValue("claims") ?? {};
        const stats = this.readValue("faucet_stats") ?? {
            id: 1,
            total_claims: 0,
            total_distributed: "0",
            unique_wallets: 0,
            last_updated_epoch: 0,
        };

        if (claims[wallet]) {
            claims[wallet].claim_count = Number(claims[wallet].claim_count ?? 0) + 1;
            claims[wallet].total_claimed = addAmounts(claims[wallet].total_claimed ?? "0", amount);
            claims[wallet].last_claim_epoch = nowEpoch;
            claims[wallet].last_tx_hash = txHash;
        } else {
            claims[wallet] = {
                wallet,
                last_claim_epoch: nowEpoch,
                claim_count: 1,
                total_claimed: parseNumber(amount, 0).toString(),
                first_claim_epoch: nowEpoch,
                last_tx_hash: txHash,
            };
            stats.unique_wallets = Number(stats.unique_wallets ?? 0) + 1;
        }

        stats.total_claims = Number(stats.total_claims ?? 0) + 1;
        stats.total_distributed = addAmounts(stats.total_distributed ?? "0", amount);
        stats.last_updated_epoch = nowEpoch;

        this.writeValue("claims", claims);
        this.writeValue("faucet_stats", stats);
        return { success: true };
    }

    getUserClaimHistory(wallet) {
        const claims = this.readValue("claims") ?? {};
        const claim = claims[wallet];
        if (!claim) return { history: [] };
        return {
            history: [
                {
                    last_claim: toIso(claim.last_claim_epoch),
                    claim_count: Number(claim.claim_count ?? 0),
                    total_claimed: String(claim.total_claimed ?? "0"),
                    last_tx_hash: String(claim.last_tx_hash ?? ""),
                    first_claim: toIso(claim.first_claim_epoch),
                },
            ],
        };
    }

    getStats() {
        const stats = this.readValue("faucet_stats") ?? {};
        return { stats };
    }

    getRoom(roomId) {
        const roomJoins = this.readValue("room_joins") ?? {};
        return { room: roomJoins[roomId] ?? null };
    }

    recordRoomJoin(roomId, roomName, nowEpoch) {
        if (!roomId) throw new Error("room_id is required");
        const roomJoins = this.readValue("room_joins") ?? {};
        roomJoins[roomId] = {
            room_id: roomId,
            joined_epoch: nowEpoch,
            welcome_sent: false,
            room_name: roomName ? String(roomName) : undefined,
        };
        this.writeValue("room_joins", roomJoins);
        return { success: true };
    }

    markWelcomeSent(roomId) {
        if (!roomId) throw new Error("room_id is required");
        const roomJoins = this.readValue("room_joins") ?? {};
        if (roomJoins[roomId]) {
            roomJoins[roomId].welcome_sent = true;
            this.writeValue("room_joins", roomJoins);
        }
        return { success: true };
    }

    getUserPreferences(wallet) {
        const preferences = this.readValue("user_preferences") ?? {};
        const prefs = preferences[wallet];
        if (!prefs) return { preferences: null };
        return {
            preferences: {
                reminders_enabled: Boolean(prefs.reminders_enabled),
                reminder_offset: Number(prefs.reminder_offset ?? 1),
                timezone: String(prefs.timezone ?? "UTC"),
                created_at: toIso(Number(prefs.created_epoch ?? 0)),
                updated_at: toIso(Number(prefs.updated_epoch ?? 0)),
            },
        };
    }

    setUserPreferences(wallet, patch, nowEpoch) {
        if (!wallet) throw new Error("wallet is required");
        const preferences = this.readValue("user_preferences") ?? {};
        const current = preferences[wallet];

        if (!current) {
            preferences[wallet] = {
                wallet,
                reminders_enabled: patch.reminders_enabled !== undefined ? Boolean(patch.reminders_enabled) : true,
                reminder_offset: patch.reminder_offset !== undefined ? Number(patch.reminder_offset) : 1,
                timezone: patch.timezone ? String(patch.timezone) : "UTC",
                created_epoch: nowEpoch,
                updated_epoch: nowEpoch,
            };
        } else {
            current.reminders_enabled =
                patch.reminders_enabled !== undefined ? Boolean(patch.reminders_enabled) : current.reminders_enabled;
            current.reminder_offset = patch.reminder_offset !== undefined ? Number(patch.reminder_offset) : current.reminder_offset;
            current.timezone = patch.timezone ? String(patch.timezone) : current.timezone;
            current.updated_epoch = nowEpoch;
        }

        this.writeValue("user_preferences", preferences);
        return { success: true };
    }

    getPendingReminders(beforeEpochInput, nowEpoch) {
        const reminders = this.readValue("scheduled_reminders") ?? [];
        const beforeEpoch = asEpoch(beforeEpochInput) ?? nowEpoch;
        const pending = reminders
            .filter((item) => !item.sent && Number(item.reminder_epoch ?? 0) <= beforeEpoch)
            .sort((a, b) => Number(a.reminder_epoch ?? 0) - Number(b.reminder_epoch ?? 0))
            .map((item) => ({
                id: Number(item.id ?? 0),
                wallet: String(item.wallet ?? ""),
                room_id: String(item.room_id ?? ""),
                reminder_time: toIso(Number(item.reminder_epoch ?? 0)),
                message: String(item.message ?? ""),
            }));
        return { reminders: pending };
    }

    scheduleReminder(request, nowEpoch) {
        const wallet = String(request.wallet ?? "");
        const roomId = String(request.room_id ?? "");
        const message = String(request.message ?? "");
        if (!wallet || !roomId || !message) throw new Error("wallet, room_id and message are required");

        const reminders = this.readValue("scheduled_reminders") ?? [];
        const nextId = Number(this.readValue("next_reminder_id") ?? 1);

        let reminderEpoch = asEpoch(request.reminder_epoch);
        if (reminderEpoch == null) {
            const cooldownHours = Number(request.cooldown_hours ?? this.cooldownHours);
            const offsetHours = Number(request.offset_hours ?? 1);
            reminderEpoch = nowEpoch + Math.max(cooldownHours - offsetHours, 0) * 3600;
        }

        reminders.push({
            id: nextId,
            wallet,
            room_id: roomId,
            reminder_epoch: reminderEpoch,
            message,
            sent: false,
            created_epoch: nowEpoch,
            sent_epoch: 0,
        });

        this.writeValue("scheduled_reminders", reminders);
        this.writeValue("next_reminder_id", nextId + 1);
        return { success: true, reminder_id: nextId };
    }

    markReminderSent(reminderId, nowEpoch) {
        const reminders = this.readValue("scheduled_reminders") ?? [];
        for (const reminder of reminders) {
            if (Number(reminder.id ?? 0) === reminderId) {
                reminder.sent = true;
                reminder.sent_epoch = nowEpoch;
                this.writeValue("scheduled_reminders", reminders);
                break;
            }
        }
        return { success: true };
    }

    setBlacklist(request, nowEpoch) {
        const wallet = String(request.wallet ?? "");
        if (!wallet) throw new Error("wallet is required");
        const blacklist = this.readValue("blacklist") ?? {};
        blacklist[wallet] = {
            wallet,
            reason: String(request.reason ?? "unspecified"),
            blacklisted_epoch: nowEpoch,
            blacklisted_by: String(request.blacklisted_by ?? "system"),
        };
        this.writeValue("blacklist", blacklist);
        return { success: true };
    }

    removeBlacklist(wallet) {
        const blacklist = this.readValue("blacklist") ?? {};
        delete blacklist[wallet];
        this.writeValue("blacklist", blacklist);
        return { success: true };
    }
}

module.exports = { faucet_contract };