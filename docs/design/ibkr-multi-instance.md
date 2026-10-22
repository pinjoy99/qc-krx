# Design: several LEAN live/paper deployments on one IBKR login

Status: **design only, nothing implemented or tested.** Written 2026-10-22 from the source of
`QuantConnect/Lean.Brokerages.InteractiveBrokers` (commit `fb86123`, 2026-10-01) and LEAN
(`80e7843`). Line numbers refer to `InteractiveBrokersBrokerage.cs` at that commit.

The same pattern will matter for qc-krx-broker (KIS): several strategies sharing one brokerage
account.

## 1. Problem

With the LEAN CLI, a second IBKR paper deployment knocks out the first. The cause isn't Docker:

1. Each deployment starts **its own IB Gateway** through IBAutomater and logs in with the same
   username (`new IBAutomater(...userName, password, tradingMode, port...)`, line 1525).
   IBKR allows **one session per username**, so the second login ends the first. Market data is
   tied to that session too (the plugin has a `CompetingLiveSessionMarketDataErrorHandler`).
2. The plugin's API **client ID is a constant 0** (`private const int ClientId = 0;`, line 125),
   so two LEAN instances can't share one gateway either; IB rejects a duplicate client ID.
3. LEAN assumes it **owns the whole account**: at start-up it loads all account cash, holdings and
   open orders (`BrokerageSetupHandler`: `GetCashBalance`, `GetAccountHoldings`,
   `GetOpenOrders`), and once a day it overwrites its cash with the account's
   (`Brokerage.PerformCashSync`). Two instances on one account would each see, and could
   liquidate, the other's positions.

## 2. Target architecture

```
            IBKR paper account (one username, one session)
                               │
                 IB Gateway (run by you, IBC keeps it logged in)
                 API port 4002, up to 32 API clients
        ┌──────────────┬───────┴──────┬──────────────┐
   client 1        client 2       client 3        client 9 (read-only)
   LEAN "A"        LEAN "B"       LEAN "C"        supervisor
   tag A, ledger A tag B, ledger B tag C, ledger C reconciles ledgers vs account
```

- **One** IB Gateway, logged in once, kept alive and restarted by IBC.
- Each LEAN instance connects as its **own API client ID** and tags its orders with its own
  **strategy tag** (`Order.OrderRef`).
- Each instance's portfolio comes from its **own ledger**, never from the account totals.
- A small **supervisor** checks that the ledgers add up to the account and alerts when they don't.

IB delivers `openOrder`, `orderStatus` and `execDetails` for an order to the client that placed it
(and to a "master client", which we won't configure), so order and fill events are already
separated per instance. Account-level data (`updatePortfolio`, account values) goes to every
client, which is why the ledger is needed.

## 3. Plugin changes

A small fork of the plugin (Apache 2.0), kept as a patch so it can be rebased on upstream. All
new settings are off by default: with them unset, behaviour is unchanged.

| # | Setting | Change | Where |
|---|---|---|---|
| 1 | `ib-client-id` (int, default 0) | Replace the constant with a field; use it in `eConnect` (line 984) and in both `ExecutionFilter`s (lines 871, 3260) | constructor, `Connect`, `GetExecutions` |
| 2 | `ib-external-gateway` (bool) | Skip IBAutomater start-up and the weekly restart task also when the gateway runs on localhost. Today this happens only for a non-loopback `ib-host` (`_isRemoteGateway`, line 1534) | constructor |
| 3 | `ib-strategy-tag` (string) | Set `ibOrder.OrderRef = tag` on every order | `ConvertOrder` (line 3258) |
| 4 | client ID ≠ 0 | `GetOpenOrders` calls only `reqOpenOrders` (this client's orders): no client-0 "binding" call, no `reqAllOpenOrders` (line 691). Also drop any open order whose `OrderRef` isn't this instance's tag | `GetOpenOrders`, `GetOpenOrdersInternal` |
| 5 | `ib-virtual-account` (bool) + `ib-virtual-cash` (amount, currency) + `ib-ledger-path` | Virtual account (section 4): `GetAccountHoldings`, `GetCashBalance` and `PerformCashSync` answer from the ledger; fills are recorded in it | new class `VirtualAccountLedger`; overrides in the brokerage |

Changes 1–4 are general-purpose; they'd be reasonable to propose upstream. Change 5 is the
part specific to this design.

Never configure a LEAN instance as client 0 in this setup: client 0 also receives orders placed
manually in TWS and is the only client that can modify them.

## 4. Keeping each instance's positions separate (virtual account)

### Ledger

One append-only file per instance (`ib-ledger-path`, JSON lines), written before the fill is
passed on to LEAN:

```json
{"type": "fill", "execId": "0000e1a7.65f1…", "permId": 123456789, "orderRef": "A",
 "symbol": "AAPL", "secType": "STK", "qty": 100, "price": 187.12, "commission": 1.00,
 "time": "2026-10-22T14:31:05Z"}
{"type": "cash", "currency": "USD", "amount": 100000, "note": "initial allocation"}
{"type": "split", "symbol": "XYZ", "factor": 0.25, "date": "2026-11-03"}
```

- **Positions** = sum of fills per symbol. **Cash** = allocations − buys + sells − commissions
  (+ dividends, if recorded).
- `execId` is unique per execution, so replaying the same fill twice is harmless.
- Use `permId` and `execId` as keys, not IB order IDs: those are per client and restart-dependent.

### Brokerage behaviour in virtual-account mode

| LEAN asks | Answer |
|---|---|
| `GetCashBalance()` (start-up) | ledger cash |
| `GetAccountHoldings()` (start-up) | ledger positions, priced with the latest account `updatePortfolio` market prices |
| `GetOpenOrders()` | own client's orders with own tag (change 4) |
| `PerformCashSync()` (daily) | resets cash to the ledger, not the account |
| `AccountChanged` events | still raised but ignored. LEAN only applies them when the brokerage says `AccountInstantlyUpdated`, which IB doesn't |
| fills (`execDetails` + `commissionReport`) | append to the ledger, then emit the LEAN order event as today |

Result: `Portfolio`, `Liquidate()`, `SetHoldings()` and the buying-power checks see **only this
instance's positions and allocated cash**. That's the safety property: instance A can't sell
B's shares.

### Recovery after a restart

1. Replay the ledger file.
2. Call `reqExecutions` with `ExecutionFilter.ClientId = this client` and add fills with unknown
   `execId`s, i.e. fills that happened while the instance was down. IB only returns recent
   executions (the current day, as far as I know), so the ledger file is the real record.
3. Load open orders (change 4).

### Supervisor (separate small process, client ID 9, read-only)

- Every N minutes: per symbol, check Σ ledger positions == account position. Check Σ ledger cash
  ≤ account cash, and the account's margin cushion.
- On a mismatch, alert and optionally tell the instances to stop trading. Causes include a manual
  TWS trade, a corporate action not in the ledgers, or a lost fill.
- It never places orders.

## 5. Rules for the strategies (version 1)

- **Partition symbols**: each instance gets an allow-list, and no symbol is traded by two
  instances. Reason: the account nets positions. A short by B against A's long becomes a plain
  sale at IBKR (no borrow, different margin), and ledgers stay right but the account doesn't
  match intuition. Lift this rule only after testing.
- **Fixed capital allocation per instance** (`ib-virtual-cash`). The account's real margin is
  shared, so the sum of allocations must stay below the account's net liquidation value with a
  buffer. The supervisor enforces it.
- Stocks/ETFs first. Options, futures and FX conversions need extra ledger rules (assignment,
  expiry, multi-currency cash) and come later.
- Corporate actions: LEAN adjusts its own holdings for splits from its data. The ledger must
  record the same split, or the supervisor's check will flag it. Either way it's a known gap to
  close.

## 6. IB Gateway setup (one per account, outside LEAN)

- **Install** IB Gateway (stable) and **IBC** (open-source login and restart automation). Run
  headless under Xvfb, as a systemd service, on the same host as the LEAN instances.
- **IBC config:** paper trading mode, your paper username/password, the auto-restart time set
  outside trading hours, and accept incoming API connections.
- **Gateway API settings:**
  - Enable ActiveX and Socket Clients
  - socket port **4002** (paper)
  - "Read-Only API" off
  - trusted IP 127.0.0.1 only
  - **"Master API client ID" empty**
- **Each LEAN instance (live config):**
  - `ib-host 127.0.0.1`, `ib-port 4002`
  - `ib-external-gateway true`
  - its own `ib-client-id` (1, 2, 3, …) and `ib-strategy-tag`
  - `ib-account DU…`, `ib-virtual-account true`, `ib-virtual-cash …`, `ib-ledger-path …`
  - `ib-user-name` / `ib-password` aren't used when the gateway is external
- **Limits to measure (they're shared by all clients of the session):**
  - market-data lines (100 by default per username); whether the same symbol subscribed by two
    clients counts once or twice is unknown
  - API message rate
  - historical-data pacing

## 7. Running it

On a LEAN source build, each instance is a separate `QuantConnect.Lean.Launcher` process in live
mode with the patched plugin DLL next to the launcher. Each has its own config: environment
`live-interactive`, the settings above, and its own results/log folder. Later this could become
`klean live deploy` (roadmap P4). This doesn't work through the LEAN CLI's IB deployment, which
starts its own gateway per container.

## 8. Test plan (IBKR paper account only)

| # | Test | Pass when |
|---|---|---|
| T0 | One instance, client 1, external gateway, virtual account off | Same behaviour as today |
| T1 | Two instances, different symbols, both trading | Each sees only its own fills; supervisor balances |
| T2 | Restart instance A mid-day with a position and a working order | A recovers exactly its position, cash and order; B unaffected |
| T3 | Fill while A is stopped (resting limit order) | Recovered from `reqExecutions` on restart |
| T4 | `Liquidate()` in A | Only A's positions close |
| T5 | Gateway restart (IBC) | Both instances reconnect and resume; no duplicated fills |
| T6 | Manual trade in TWS | Supervisor flags the mismatch; instances unaffected |
| T7 | Market-data lines | Measure line usage with 2–3 instances on overlapping symbols |

## 9. Risks and open questions

- **Upstream drift:** the plugin changes often; keep the patch small (changes 1–4 are a few lines
  each) and rebase per release.
- **IB behaviour to confirm on paper:** delivery of `execDetails` only to the placing client;
  `reqExecutions` history length; market-data line accounting per client; gateway restart and
  reconnect timing.
- **Shared margin:** a single instance can still be rejected for account-level margin caused by
  others; allocations must be conservative.
- **Ledger correctness** is now critical (dividends, splits, fees, FX). The supervisor's
  reconciliation is the guard; never trade a real account until T0–T7 pass.
- **IBKR terms:** several API clients on one session is a normal IB Gateway feature. Still,
  confirm your account type has no extra restrictions before using it with a real account.

## 10. Alternatives (for comparison)

- **One LEAN deployment running all strategies** (LEAN's Framework with several alpha models).
  No plugin change; the strategies share a lifecycle.
- **Separate IBKR users or accounts** per deployment. No code change; costs per user for market
  data, and needs separate paper accounts.
