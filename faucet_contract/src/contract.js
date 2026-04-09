const HotPocket = require('hotpocket-nodejs-contract');
const { faucet_contract } = require('./faucet_contract');

const app = new faucet_contract({
    cooldownHours: Number.parseInt(process.env.FAUCET_COOLDOWN_HOURS ?? "24", 10),
});

app.sendOutput = async (user, output) => {
    await user.send(output);
};

// HotPocket smart contract is defined as a function which takes the HotPocket contract context as an argument.
// This function gets invoked every consensus round and whenever a user sends a out-of-concensus read-request.
async function contract(ctx) {
    // In 'readonly' mode, nothing our contract does will get persisted on the ledger. The benefit is
    // readonly messages gets processed much faster due to not being subjected to consensus.
    // We should only use readonly mode for returning/replying data for the requesting user.
    //
    // In consensus mode (NOT read-only), we can do anything like persisting to data storage and/or
    // sending data to any connected user at the time. Everything will get subjected to consensus so
    // there is a time-penalty.
    const isReadOnly = ctx.readonly;

    // Process user inputs.
    // Loop through list of users who have sent us inputs.
    for (const user of ctx.users.list()) {

        // Loop through inputs sent by each user.
        for (const input of user.inputs) {

            // Read the data buffer sent by user (this can be any kind of data like string, json or binary data).
            const buf = await ctx.users.read(input);

            // Let's assume all data buffers for this contract are JSON.
            // In real-world apps, we need to gracefully filter out invalid data formats for our contract.
            let message;
            try {
                message = JSON.parse(buf);
            } catch {
                await app.sendOutput(user, {
                    v: 1,
                    id: null,
                    ok: false,
                    cmd: "unknown",
                    error: { code: "INVALID_JSON", message: "Input must be valid JSON" },
                });
                continue;
            }

            // Pass the JSON message to our application logic component.
            await app.handleRequest(user, message, {
                isReadOnly,
                epoch: ctx.timestamp,
                ledgerSeqNo: ctx.lclSeqNo ?? null,
            });
        }
    }
}

const hpc = new HotPocket.Contract();
hpc.init(contract);