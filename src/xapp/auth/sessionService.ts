import crypto from "node:crypto";

import { IdentityLinkStore, type IdentityLink } from "../../storage/identityLinkStore.js";

export interface XAppSessionClaims {
  sub: string;
  wallet: string;
  matrix_user_id: string;
  xaman_account: string;
  iat: number;
  exp: number;
  iss: string;
  aud: string;
}

export class SessionService {
  private readonly consumedOttHashes = new Set<string>();

  constructor(
    private readonly identityStore: IdentityLinkStore,
    private readonly sessionSecret: string,
    private readonly sessionTtlSeconds: number,
    private readonly issuer: string,
    private readonly audience: string,
    private readonly homeserverDomain: string,
  ) {}

  exchangeOtt(input: {
    ott: string;
    walletAddress: string;
    xamanAccount?: string;
    matrixUserId?: string;
  }): { token: string; link: IdentityLink } {
    if (!input.ott || input.ott.length < 8) {
      throw new Error("Invalid OTT");
    }
    const ottHash = hashText(input.ott);
    if (this.consumedOttHashes.has(ottHash)) {
      throw new Error("OTT already used");
    }

    const xamanAccount = input.xamanAccount ?? input.walletAddress;
    const matrixUserId = input.matrixUserId ?? this.defaultMatrixUserId(input.walletAddress);
    const link = this.identityStore.upsertLink({
      walletAddress: input.walletAddress,
      matrixUserId,
      xamanAccount,
    });

    this.consumedOttHashes.add(ottHash);
    const token = this.signToken({
      sub: link.wallet_address,
      wallet: link.wallet_address,
      matrix_user_id: link.matrix_user_id,
      xaman_account: link.xaman_account,
      iat: Math.trunc(Date.now() / 1000),
      exp: Math.trunc(Date.now() / 1000) + this.sessionTtlSeconds,
      iss: this.issuer,
      aud: this.audience,
    });

    return { token, link };
  }

  verifyToken(token: string): XAppSessionClaims {
    const [headerB64, payloadB64, signature] = token.split(".");
    if (!headerB64 || !payloadB64 || !signature) {
      throw new Error("Malformed token");
    }
    const expected = sign(`${headerB64}.${payloadB64}`, this.sessionSecret);
    if (!timingSafeEqual(signature, expected)) {
      throw new Error("Invalid token signature");
    }
    const payload = JSON.parse(Buffer.from(payloadB64, "base64url").toString("utf8")) as XAppSessionClaims;
    const now = Math.trunc(Date.now() / 1000);
    if (payload.exp <= now) throw new Error("Token expired");
    if (payload.iss !== this.issuer) throw new Error("Invalid token issuer");
    if (payload.aud !== this.audience) throw new Error("Invalid token audience");
    return payload;
  }

  private signToken(claims: XAppSessionClaims): string {
    const header = { alg: "HS256", typ: "JWT" };
    const headerB64 = Buffer.from(JSON.stringify(header)).toString("base64url");
    const payloadB64 = Buffer.from(JSON.stringify(claims)).toString("base64url");
    const signature = sign(`${headerB64}.${payloadB64}`, this.sessionSecret);
    return `${headerB64}.${payloadB64}.${signature}`;
  }

  private defaultMatrixUserId(wallet: string): string {
    const localpart = `xapp_${wallet.replace(/[^a-zA-Z0-9]/g, "").slice(0, 24).toLowerCase()}`;
    return `@${localpart}:${this.homeserverDomain}`;
  }
}

function sign(value: string, secret: string): string {
  return crypto.createHmac("sha256", secret).update(value).digest("base64url");
}

function hashText(value: string): string {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function timingSafeEqual(a: string, b: string): boolean {
  const aBuf = Buffer.from(a);
  const bBuf = Buffer.from(b);
  if (aBuf.length !== bBuf.length) return false;
  return crypto.timingSafeEqual(aBuf, bBuf);
}
