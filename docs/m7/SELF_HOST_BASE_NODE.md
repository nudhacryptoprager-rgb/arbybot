# M7.E1.51 slice-7 — Self-host Base node plan

> Goal: eliminate public-RPC rate limits (drpc 429 on `eth_subscribe`) by
> running our own Base archive/full node. Cost-benefit favors self-host
> when monthly third-party RPC + private mempool spend exceeds ~$200.

## Hardware target

| Tier              | Provider / SKU            | Monthly | Notes                                      |
| ----------------- | ------------------------- | ------- | ------------------------------------------ |
| **Recommended**   | Hetzner AX52 (Ryzen 7950X)| ~$60    | 64GB ECC, 2x1.92TB NVMe RAID-0, 1Gbps      |
| Stretch           | Hetzner AX102 (i9-14900)  | ~$120   | 128GB ECC, 2x1.92TB NVMe, 10Gbps add-on    |
| Cloud (expensive) | AWS i4i.2xlarge           | ~$430   | not recommended; egress kills budget       |

Disk: Base mainnet full node ~750GB and growing ~30GB/month.
Archive: ~3.5TB. Start with **full** (not archive) — sim backends only
need recent state.

## Software stack

```bash
# OS: Ubuntu 22.04 LTS
# Client: op-geth + op-node (Optimism stack, Base shares it)

# 1. L1 RPC dependency — Base requires an L1 (Ethereum mainnet) RPC.
#    Cheapest: Alchemy free tier (300M CU/mo) is enough for Base sync.
export L1_RPC=https://eth-mainnet.g.alchemy.com/v2/<KEY>
export L1_BEACON=https://www.lightclientdata.org

# 2. Snapshot bootstrap (avoids 7-day genesis sync)
wget https://snapshots.base.org/base-mainnet/snapshot-latest.tar.lz4
lz4 -d snapshot-latest.tar.lz4 | tar -x -C /var/lib/base

# 3. Run op-geth
op-geth --datadir /var/lib/base --syncmode snap \
        --rollup.disabletxpoolgossip=false \
        --http --http.addr 0.0.0.0 --http.port 8545 \
        --http.api eth,net,web3,debug,txpool \
        --ws --ws.addr 0.0.0.0 --ws.port 8546 \
        --ws.api eth,net,web3,debug,txpool

# 4. Run op-node (consensus layer)
op-node --l1=$L1_RPC --l1.beacon=$L1_BEACON \
        --l2=ws://localhost:8551 --l2.jwt-secret=/var/lib/base/jwt.hex \
        --network=base-mainnet --rpc.addr=0.0.0.0 --rpc.port=9545
```

## Sync timeline

- **Snap-sync from snapshot**: ~6-12h on AX52 NVMe RAID-0
- **Full sync from genesis**: ~7 days (avoid this)
- **Catch-up after restart**: ~5-30 min depending on downtime

During sync, **fall back to public RPC** in our scanner. ENV switch:

```yaml
# config/real_minimal.yaml
rpc:
  base:
    primary:   "ws://10.0.0.5:8546"        # self-hosted
    fallback:  "wss://base.drpc.org"       # public during sync
    health_check_url: "http://10.0.0.5:8545"
```

## Monitoring

| Metric                                | Alert if                  |
| ------------------------------------- | ------------------------- |
| `op-geth` peer count                  | < 5                       |
| Block height vs `https://basescan.org`| lag > 30 blocks           |
| Disk free                             | < 200GB                   |
| `eth_blockNumber` p95 latency         | > 50ms                    |
| Restart count (24h)                   | > 1                       |

Recommended: `prometheus + node_exporter + op-geth metrics endpoint`.

## Cost-benefit

Current third-party stack we are paying for / hitting limits on:

- drpc free tier: 429 every ~3min on `eth_subscribe newHeads`
- public Base RPC: same
- Tenderly dev tier: insufficient for prod sim load

Self-host break-even calc:

```
Hetzner AX52       : $60/mo
L1 Alchemy free    : $0   (300M CU/mo)
Bandwidth (1TB/mo) : included
Total              : $60/mo

vs equivalent third-party for unlimited eth_subscribe + sim:
- Alchemy Growth   : $199/mo  (still rate-limited)
- QuickNode Build  : $299/mo
- Coinbase Cloud   : $5000+/mo (only true unlimited)
```

Break-even: **<1 month** vs Alchemy Growth, **<5 days** vs Coinbase Cloud.

## Acceptance (slice-7 sign-off)

This slice delivers **plan documentation only**. Real provisioning is a
manual ops step. Acceptance is met when:

1. Hetzner box ordered + IP recorded in ops vault
2. Snapshot import succeeds, op-geth + op-node running
3. `eth_blockNumber` returns within 5 blocks of `basescan.org` for 1h
4. Switch `rpc.base.primary` in `config/real_minimal.yaml` to self-host URL
5. 30m canary (slice-8) shows `ws_429_delta == 0` on logs subscription

If any step fails, document in `docs/m7/SELF_HOST_BASE_NODE_DEPLOY_LOG.md`
and roll back `rpc.base.primary` to public fallback.

## Failure modes

| Symptom                          | Diagnostic                          | Action                              |
| -------------------------------- | ----------------------------------- | ----------------------------------- |
| Stuck at block N for >10min      | `op-node` log: `engine_forkchoice`  | restart op-node, check L1 RPC       |
| Disk filling fast                | `du -sh /var/lib/base`              | enable pruning (`--gcmode=full`)    |
| Sequencer unreachable            | DNS / firewall                      | open egress to `mainnet.base.org`   |
| L1 RPC quota exhausted           | Alchemy dashboard 429               | upgrade or add second L1 provider   |

## Slice-7 verdict

Documentation only. Expected outcome of execution: drpc 429 elimination,
which is the original E1.50 root cause. Execution gated on ops decision.
