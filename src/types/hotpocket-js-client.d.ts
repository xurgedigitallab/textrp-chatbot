declare module "hotpocket-js-client" {
  export const events: {
    disconnect: string;
    contractOutput: string;
  };

  export function generateKeys(): Promise<{
    privateKey: string;
    publicKey: string;
  }>;

  export function createClient(
    servers: string[],
    keyPair: { privateKey: string; publicKey: string },
  ): Promise<{
    connect(): Promise<boolean>;
    close(): void;
    on(event: string, handler: (payload: any) => void): void;
    getStatus(): Promise<{ ledgerSeqNo: number }>;
    submitContractInput(payload: string): Promise<{
      submissionStatus: Promise<{ status: string; reason?: string }>;
    }>;
    submitContractReadRequest(payload: string): Promise<any>;
  }>;
}
