const XRP_CLASSIC_ADDRESS = /^r[1-9A-HJ-NP-Za-km-z]{24,34}$/;

export function extractWalletFromUserId(userId: string): string | null {
  if (!userId.startsWith("@") || !userId.includes(":")) return null;
  const localpart = userId.slice(1).split(":")[0];
  if (XRP_CLASSIC_ADDRESS.test(localpart)) return localpart;
  return null;
}

export function shortHash(value: string): string {
  if (value.length < 20) return value;
  return `${value.slice(0, 12)}...${value.slice(-8)}`;
}

