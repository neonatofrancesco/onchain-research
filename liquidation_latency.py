"""
Liquidation latency across Ethereum lending protocols (data for notes/01_liquidation_latency.md).

Protocols: Aave v3 Core, Aave v3 Lido (smaller instance), SparkLend, Morpho Blue, Compound v3 (6 markets).
Fixed window: 2025-10-01 00:00 -> 2026-10-01 00:00 UTC (includes the 10 October 2025 crash).

Question: once a position becomes liquidatable, how many blocks pass before it is liquidated? Systematic
delays on liquid collateral would leave room for a new liquidator; otherwise the race is already won by the
fastest incumbents.

Method, for each relevant liquidation (repaid debt >= $1,000 at DefiLlama daily prices):
  1. Only the FIRST liquidation of each episode: if the same position was liquidated in the previous 7,200
     blocks, the event is a follow-up (Aave liquidates at most 50% at a time) and its delay does not measure
     competition. Follow-ups are counted separately.
  2. Latency = blocks between the first block in which the position was liquidatable and the liquidation block
     (0 = same block: a backrun of the price update). Exponential then binary search backwards, up to 7,200
     blocks (1 day), on free archive RPCs in parallel.
       Aave/Spark: health factor < 1 from getUserAccountData (includes accrued interest)
       Morpho:     debt (including accrued but unbooked interest, via the IRM) > collateral x price x LLTV
       Compound:   isLiquidatable(account)
  3. Gross bonus at the protocol ORACLE's prices in the block, gas from the receipt (Aave/Spark/Morpho).
     Compound v3 pays no bonus to whoever calls absorb (the profit is in buying the collateral at a discount):
     latency only.

Stated limitations: only positions that were actually liquidated are observed (those that recovered on their
own do not appear); net profit excludes builder tips paid by transfer, resale slippage and flash-loan costs.

Requires BLOCKSCOUT_API_KEY in .env. The first run takes about an hour (cached in data/, resumes where it
stopped). Run: python liquidation_latency.py [--test]
"""

import bisect
import csv
import datetime as dt
import json
import math
import os
import random
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from eth_abi import decode
from eth_utils import keccak, to_checksum_address

from chain import DATA, ROOT, blockscout_get, blockscout_logs, get_w3, make_w3

START = dt.datetime(2025, 10, 1, tzinfo=dt.UTC)
END = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
LOGS_CACHE = os.path.join(DATA, "cache_liq_logs_2025-10_2026-10.json")
META_CACHE = os.path.join(DATA, "cache_liq_meta.json")
PRICE_CACHE = os.path.join(DATA, "cache_llama_prices.json")
RESULTS = os.path.join(DATA, "cache_liq_latency.jsonl")
CAUSE = os.path.join(DATA, "cache_liq_cause.jsonl")
CSV_OUT = os.path.join(DATA, "liquidation_latency.csv")
ARCHIVES = ["https://eth.drpc.org", "https://eth-mainnet.public.blastapi.io", "https://rpc.mevblocker.io"]
WORKERS_PER_RPC = 2
MAX_LOOKBACK = 7200
MIN_SIZE = 1_000
MAX_PER_PROTO = 1_500        # above this, a random sample (fixed seed): enough for tight confidence intervals
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

AAVE_LIQ = "0x" + keccak(text="LiquidationCall(address,address,address,uint256,uint256,address,bool)").hex()
MORPHO_LIQ = "0x" + keccak(text="Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()
ABS_DEBT = "0x" + keccak(text="AbsorbDebt(address,address,uint256,uint256)").hex()
ABS_COLL = "0x" + keccak(text="AbsorbCollateral(address,address,address,uint256,uint256)").hex()
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
# Comet addresses: github.com/compound-finance/comet/tree/main/deployments/mainnet (checked 2026-10-13)
COMETS = {"USDC": "0xc3d688B66703497DAA19211EEdff47f25384cdc3", "USDT": "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840",
          "WETH": "0xA17581A9E3356d9A858b789D68B4d866e593aE94", "wstETH": "0x3D0bb1ccaB520A66e607822fC55BC921738fAFE3",
          "USDS": "0x5D409e56D886231aDAf00c8775665AD0f9897b56", "WBTC": "0xe85Dc543813B8c2CFEaAc371517b925a166a9293"}
AAVE_POOLS = {"Aave v3 Core": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
              "Aave v3 Lido": "0x4e033931ad43597d96D6bcc25c280717730B58B1",
              "SparkLend": "0xC13e21B648A5Ee794902342038FF3aDAB66BE987"}
PROTOS = list(AAVE_POOLS) + ["Morpho Blue", "Compound v3"]
BLUE_CHIP = {"WETH", "ETH", "wstETH", "weETH", "rETH", "cbETH", "osETH", "ETHx", "WBTC", "cbBTC", "tBTC", "LBTC",
             "USDC", "USDT", "DAI", "USDS", "sDAI", "sUSDS", "PYUSD", "GHO", "USDe", "sUSDe", "RLUSD", "USDtb", "LINK",
             "AAVE", "COMP", "UNI"}


def fn(name, inputs=(), outputs=("uint256",)):
    return {"name": name, "type": "function", "stateMutability": "view",
            "inputs": [{"name": f"a{i}", "type": t} for i, t in enumerate(inputs)],
            "outputs": [{"name": f"o{i}", "type": t} for i, t in enumerate(outputs)]}


ERC20 = [fn("symbol", outputs=("string",)), fn("decimals", outputs=("uint8",)), fn("totalSupply")]
AAVE_POOL = [fn("getUserAccountData", ("address",), ("uint256",) * 6), fn("ADDRESSES_PROVIDER", outputs=("address",)),
             fn("getReservesList", outputs=("address[]",))]
PROVIDER = [fn("getPriceOracle", outputs=("address",))]
ORACLE = [fn("getAssetPrice", ("address",))]
MORPHO_ABI = [fn("idToMarketParams", ("bytes32",), ("address", "address", "address", "address", "uint256")),
              fn("market", ("bytes32",), ("uint128",) * 6),
              fn("position", ("bytes32", "address"), ("uint256", "uint128", "uint128"))]
PRICE = [fn("price")]
IRM = [{"name": "borrowRateView", "type": "function", "stateMutability": "view", "outputs": [{"name": "", "type": "uint256"}],
        "inputs": [{"name": "mp", "type": "tuple", "components": [{"name": n, "type": t} for n, t in
                    (("loanToken", "address"), ("collateralToken", "address"), ("oracle", "address"), ("irm", "address"), ("lltv", "uint256"))]},
                   {"name": "m", "type": "tuple", "components": [{"name": n, "type": "uint128"} for n in
                    ("totalSupplyAssets", "totalSupplyShares", "totalBorrowAssets", "totalBorrowShares", "lastUpdate", "fee")]}]}]
COMET = [fn("isLiquidatable", ("address",), ("bool",)), fn("baseToken", outputs=("address",))]


# ------------------------------------------------------------------ raw data (Blockscout, metadata, prices)
def block_at(ts, closest):
    r = blockscout_get({"module": "block", "action": "getblocknobytime", "timestamp": int(ts.timestamp()), "closest": closest})
    return int(r["blockNumber"] if isinstance(r, dict) else r)


def load_logs():
    cache = json.load(open(LOGS_CACHE)) if os.path.exists(LOGS_CACHE) else {}
    if "b0" not in cache:
        cache = {"b0": block_at(START, "after"), "b1": block_at(END, "before"), "logs": {}}
    wanted = {**{k: (a, AAVE_LIQ) for k, a in AAVE_POOLS.items()}, "Morpho": (MORPHO, MORPHO_LIQ),
              **{f"Comet {k}": (a, ABS_DEBT) for k, a in COMETS.items()},
              **{f"Comet {k} coll": (a, ABS_COLL) for k, a in COMETS.items()}}
    changed = False
    for k, (addr, topic) in wanted.items():
        if k not in cache["logs"]:
            cache["logs"][k], _ = blockscout_logs(addr, topic, cache["b0"], cache["b1"])
            print(f"   downloaded {len(cache['logs'][k]):6} events: {k}", flush=True)
            changed = True
    if changed:
        json.dump(cache, open(LOGS_CACHE, "w"))
    return cache


def load_meta(w3, cache):
    meta = json.load(open(META_CACHE)) if os.path.exists(META_CACHE) else {"tokens": {}, "markets": {}, "oracles": {}}
    m = w3.eth.contract(address=MORPHO, abi=MORPHO_ABI)
    for mid in {l["topics"][1] for l in cache["logs"]["Morpho"]} - set(meta["markets"]):
        meta["markets"][mid] = m.functions.idToMarketParams(bytes.fromhex(mid[2:])).call()
    for name, pool in AAVE_POOLS.items():
        if name not in meta["oracles"]:
            prov = w3.eth.contract(address=pool, abi=AAVE_POOL).functions.ADDRESSES_PROVIDER().call()
            meta["oracles"][name] = w3.eth.contract(address=prov, abi=PROVIDER).functions.getPriceOracle().call()
    if "listed" not in meta:                           # assets approved by Aave Core and Spark governance
        meta["listed"] = sorted({a for n in ("Aave v3 Core", "SparkLend") for a in
                                 w3.eth.contract(address=AAVE_POOLS[n], abi=AAVE_POOL).functions.getReservesList().call()})
    tokens = {WETH} | set(meta["listed"])
    for name in AAVE_POOLS:
        for l in cache["logs"][name]:
            tokens |= {to_checksum_address("0x" + l["topics"][i][-40:]) for i in (1, 2)}
    for loan, coll, *_ in meta["markets"].values():
        tokens |= {loan, coll}
    for k, a in COMETS.items():
        tokens.add(w3.eth.contract(address=a, abi=COMET).functions.baseToken().call())
        tokens |= {to_checksum_address("0x" + l["topics"][3][-40:]) for l in cache["logs"][f"Comet {k} coll"]}
    for t in tokens - set(meta["tokens"]):
        c = w3.eth.contract(address=t, abi=ERC20)
        try:
            meta["tokens"][t] = [c.functions.symbol().call(), c.functions.decimals().call()]
        except Exception:
            meta["tokens"][t] = [t[:8], 18]
    # supply of debt tokens: used to discard tokens with inconsistent decimals (see coherent_price)
    meta.setdefault("supply", {})
    debt_side = {to_checksum_address("0x" + l["topics"][2][-40:]) for n in AAVE_POOLS for l in cache["logs"][n]}
    for t in (debt_side | {mp[0] for mp in meta["markets"].values()}) - set(meta["supply"]):
        try:
            meta["supply"][t] = w3.eth.contract(address=t, abi=ERC20).functions.totalSupply().call()
        except Exception:
            meta["supply"][t] = None
    json.dump(meta, open(META_CACHE, "w"))
    return meta


def load_prices(tokens):
    """DefiLlama daily closes (free, coins.llama.fi). Used for the size threshold and for gas."""
    prices = json.load(open(PRICE_CACHE)) if os.path.exists(PRICE_CACHE) else {}
    for t in sorted(set(tokens) - set(prices)):
        r = requests.get(f"https://coins.llama.fi/chart/ethereum:{t}",
                         params={"start": int(START.timestamp()) - 2 * 86400, "span": 370, "period": "1d"}, timeout=30)
        pts = (r.json().get("coins", {}).get(f"ethereum:{t}", {}) or {}).get("prices", []) if r.ok else []
        prices[t] = {dt.datetime.fromtimestamp(p["timestamp"], dt.UTC).date().isoformat(): p["price"] for p in pts}
        time.sleep(0.3)
    json.dump(prices, open(PRICE_CACHE, "w"))
    return prices


def px(prices, token, day):
    s = prices.get(token) or {}
    for k in range(4):                                   # tolerate missing days
        v = s.get((day - dt.timedelta(days=k)).isoformat())
        if v:
            return v
    return None


def coherent_price(meta, prices, token, day):
    """Daily price, or None if supply x price exceeds $1 trillion: a sign that decimals() does not match the
    token's real units (case found: wUSDL reports 6 decimals but its shares have 18, so its liquidations came
    out at $10^14)."""
    p = px(prices, token, day)
    sup = meta.get("supply", {}).get(token)
    if p is not None and sup and sup / 10 ** meta["tokens"][token][1] * p > 1e12:
        return None
    return p


# ------------------------------------------------------------------ normalised events
def parse_events(cache, meta, prices):
    sym = lambda a: meta["tokens"].get(a, [a[:8], 18])
    canon = {a for a in meta["listed"] if sym(a)[0] in BLUE_CHIP} | set(COMETS.values())
    canon |= {to_checksum_address("0x" + l["topics"][3][-40:]) for k in COMETS for l in cache["logs"][f"Comet {k} coll"]
              if sym(to_checksum_address("0x" + l["topics"][3][-40:]))[0] in BLUE_CHIP}
    evs = []
    for name in AAVE_POOLS:
        for l in cache["logs"][name]:
            t = l["topics"]
            debt_amt, coll_amt, liquidator, _ = decode(["uint256", "uint256", "address", "bool"], bytes.fromhex(l["data"][2:]))
            coll, debt = (to_checksum_address("0x" + t[i][-40:]) for i in (1, 2))
            user = to_checksum_address("0x" + t[3][-40:])
            evs.append(dict(proto=name, coll=coll, debt=debt, user=user, key=user, debt_amt=debt_amt, coll_amt=coll_amt,
                            liquidator=to_checksum_address(liquidator), bad_debt=0, raw=l))
    for l in cache["logs"]["Morpho"]:
        t = l["topics"]
        repaid, _, seized, bad_assets, _ = decode(["uint256"] * 5, bytes.fromhex(l["data"][2:]))
        loan, coll, *_ = meta["markets"][t[1]]
        user = to_checksum_address("0x" + t[3][-40:])
        evs.append(dict(proto="Morpho Blue", mid=t[1], coll=coll, debt=loan, user=user, key=t[1] + user, debt_amt=repaid,
                        coll_amt=seized, liquidator=to_checksum_address("0x" + t[2][-40:]), bad_debt=bad_assets, raw=l))
    for k, comet in COMETS.items():
        colls = defaultdict(list)
        for l in cache["logs"][f"Comet {k} coll"]:
            _, usd = decode(["uint256", "uint256"], bytes.fromhex(l["data"][2:]))
            colls[(l["transactionHash"], l["topics"][2])].append((usd, to_checksum_address("0x" + l["topics"][3][-40:])))
        for l in cache["logs"][f"Comet {k}"]:
            _, usd = decode(["uint256", "uint256"], bytes.fromhex(l["data"][2:]))
            c = max(colls.get((l["transactionHash"], l["topics"][2]), [(0, None)]))[1]
            user = to_checksum_address("0x" + l["topics"][2][-40:])
            evs.append(dict(proto="Compound v3", comet=comet, base=k, coll=c, debt=None, user=user, key=comet + user,
                            debt_amt=0, coll_amt=0, liquidator=to_checksum_address("0x" + l["topics"][1][-40:]),
                            bad_debt=0, debt_usd=usd / 1e8, raw=l))
    for e in evs:
        l = e.pop("raw")
        e.update(block=int(l["blockNumber"], 16), tx=l["transactionHash"], log_index=int(l["logIndex"] or "0x0", 16),
                 ts=int(l["timeStamp"], 16))
        e["day"] = dt.datetime.fromtimestamp(e["ts"], dt.UTC).date()
        e["id"] = f"{e['tx']}:{e['log_index']}"
        if e["proto"] == "Compound v3":
            e["pair"] = f"{sym(e['coll'])[0] if e['coll'] else '?'}->{e['base']}"
        else:
            p = coherent_price(meta, prices, e["debt"], e["day"])
            e["debt_usd"] = None if p is None else e["debt_amt"] / 10 ** sym(e["debt"])[1] * p
            e["pair"] = f"{sym(e['coll'])[0]}->{sym(e['debt'])[0]}"
            if e["bad_debt"] and p is not None:
                e["bad_debt_usd"] = e["bad_debt"] / 10 ** sym(e["debt"])[1] * p
        # blue-chip: symbol on the list AND canonical address (listed on Aave/Spark or Compound). The symbol alone
        # is not enough: anyone can deploy a token called "USDC" and a Morpho market that uses it.
        e["blue"] = all(a in canon for a in (e["coll"], e["debt"] if e["proto"] != "Compound v3" else e["comet"]))
    # episodes: first liquidation of a position after at least MAX_LOOKBACK blocks without liquidations
    evs.sort(key=lambda e: (e["block"], e["log_index"]))
    last = {}
    for e in evs:
        k = (e["proto"], e["key"])
        e["first"] = k not in last or e["block"] - last[k] > MAX_LOOKBACK
        last[k] = e["block"]
    return evs


# ------------------------------------------------------------------ archive measurements (in parallel)
_local = threading.local()
_counter = iter(range(10**6))
_lock = threading.Lock()


def arch():
    if not hasattr(_local, "w3"):
        with _lock:
            i = next(_counter)
        _local.w3 = make_w3(ARCHIVES[i % len(ARCHIVES)], timeout=30, retry=False)
    return _local.w3


def retry(f, tries=6):
    for i in range(tries):
        try:
            return f()
        except Exception as ex:
            msg = str(ex)
            if "execution reverted" in msg or i == tries - 1:
                raise
            time.sleep(3 * (i + 1) * (3 if "429" in msg or "Too Many" in msg else 1))


def w_taylor(x, n):
    """Morpho's compounding approximation (wTaylorCompounded)."""
    first = x * n
    second = first * first // (2 * 10**18)
    return first + second + second * first // (3 * 10**18)


def liquidatable(e, block, meta):
    w3 = arch()
    if e["proto"] in AAVE_POOLS:
        c = w3.eth.contract(address=AAVE_POOLS[e["proto"]], abi=AAVE_POOL)
        return c.functions.getUserAccountData(e["user"]).call(block_identifier=block)[5] < 10**18
    if e["proto"] == "Compound v3":
        return w3.eth.contract(address=e["comet"], abi=COMET).functions.isLiquidatable(e["user"]).call(block_identifier=block)
    mp = meta["markets"][e["mid"]]
    m = w3.eth.contract(address=MORPHO, abi=MORPHO_ABI)
    mid = bytes.fromhex(e["mid"][2:])
    _, borrow_sh, collateral = m.functions.position(mid, e["user"]).call(block_identifier=block)
    if borrow_sh == 0:
        return False
    mk = list(m.functions.market(mid).call(block_identifier=block))
    if mp[3] != "0x0000000000000000000000000000000000000000":       # interest accrued but not yet booked
        elapsed = max(0, e["ts"] - 12 * (e["block"] - block) - mk[4])   # block time estimated at 12 s per slot
        if elapsed:
            rate = w3.eth.contract(address=mp[3], abi=IRM).functions.borrowRateView(tuple(mp), tuple(mk)).call(block_identifier=block)
            mk[2] += mk[2] * w_taylor(rate, elapsed) // 10**18
    borrowed = -(-borrow_sh * (mk[2] + 1) // (mk[3] + 10**6))         # Morpho virtual shares, rounded up
    price = w3.eth.contract(address=mp[2], abi=PRICE).functions.price().call(block_identifier=block)
    return borrowed > collateral * price // 10**36 * mp[4] // 10**18


def latency(e, meta):
    B = e["block"]
    if not retry(lambda: liquidatable(e, B - 1, meta)):
        return 0
    step, good = 1, B - 1
    while step <= MAX_LOOKBACK:
        probe = B - 1 - step
        if not retry(lambda: liquidatable(e, probe, meta)):
            lo, hi = probe, good
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if retry(lambda: liquidatable(e, mid, meta)):
                    hi = mid
                else:
                    lo = mid
            return B - hi
        good, step = probe, step * 2
    return MAX_LOOKBACK


def value(e, meta, prices):
    """Gross bonus at the protocol oracle's prices in the block; gas in USD; transaction sender."""
    w3, b = arch(), e["block"]
    tok = lambda a: meta["tokens"].get(a, [a[:8], 18])
    gross = None
    if e["proto"] in AAVE_POOLS:
        o = w3.eth.contract(address=meta["oracles"][e["proto"]], abi=ORACLE)
        pc = retry(lambda: o.functions.getAssetPrice(e["coll"]).call(block_identifier=b)) / 1e8
        pd = retry(lambda: o.functions.getAssetPrice(e["debt"]).call(block_identifier=b)) / 1e8
        gross = e["coll_amt"] / 10 ** tok(e["coll"])[1] * pc - e["debt_amt"] / 10 ** tok(e["debt"])[1] * pd
    elif e["proto"] == "Morpho Blue":
        mp = meta["markets"][e["mid"]]
        price = retry(lambda: w3.eth.contract(address=mp[2], abi=PRICE).functions.price().call(block_identifier=b))
        p_loan = coherent_price(meta, prices, e["debt"], e["day"])
        if p_loan is not None:
            gross = (e["coll_amt"] * price / 10**36 - e["debt_amt"]) / 10 ** tok(e["debt"])[1] * p_loan
    rc = retry(lambda: w3.eth.get_transaction_receipt(e["tx"]))
    gas = rc["gasUsed"] * rc["effectiveGasPrice"] / 1e18 * (px(prices, WETH, e["day"]) or 0)
    return gross, gas, rc["from"]


def measure(e, meta, prices):
    out = {"id": e["id"]}
    try:
        out["lat"] = latency(e, meta)
        out["gross"], out["gas"], out["sender"] = value(e, meta, prices)
    except Exception as ex:
        out["err"] = f"{type(ex).__name__}: {str(ex)[:120]}"
    return out


# ------------------------------------------------------------------ statistics
def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def bucket(x):
    return "0" if x == 0 else "1" if x == 1 else "2-5" if x <= 5 else "6-50" if x <= 50 else "51-7199" if x < MAX_LOOKBACK else ">=1d"


BUCKETS = ["0", "1", "2-5", "6-50", "51-7199", ">=1d"]


# ------------------------------------------------------------------ causes of delays
def price_move(e, meta):
    """Does the oracle price (collateral or debt) change in the first liquidatable block? If not, the position
    became liquidatable through accrued interest (or something else, e.g. changed parameters), with no visible event."""
    hi = e["block"] - e["lat"]
    o = arch().eth.contract(address=meta["oracles"][e["proto"]], abi=ORACLE)
    get = lambda a, b: retry(lambda: o.functions.getAssetPrice(a).call(block_identifier=b))
    return {"id": e["id"], "move": any(get(a, hi) != get(a, hi - 1) for a in (e["coll"], e["debt"]))}


def causes(evs, summary, meta):
    print("\n9. Why do some liquidations arrive late? (Aave v3 Core, Aave v3 Lido, SparkLend; blue-chip only)")
    # (a) load: liquidations (all protocols, all sizes) within +-25 blocks (5 minutes) of the first liquidatable
    #     block. In a cascade many positions become liquidatable together.
    blocks = sorted(e["block"] for e in evs)
    aave = [e for p in AAVE_POOLS for e in summary[p] if e["blue"]]
    for e in aave:
        hi = e["block"] - e["lat"]
        e["load"] = bisect.bisect_right(blocks, hi + 25) - bisect.bisect_left(blocks, hi - 25)
    q = sorted(e["load"] for e in aave)
    t1, t2 = q[len(q) // 3], q[2 * len(q) // 3]
    print(f"   (a) load = liquidations within +-25 blocks (5 min) of the first liquidatable block; tertiles {t1} and {t2}")
    for lab, sel in (("low", [e for e in aave if e["load"] <= t1]), ("medium", [e for e in aave if t1 < e["load"] <= t2]),
                     ("high", [e for e in aave if e["load"] > t2])):
        k = sum(e["lat"] >= 2 for e in sel)
        lo, hi = wilson(k, len(sel))
        print(f"       {lab:6} load: {len(sel):5} episodes, delay >= 2 blocks {100 * k / len(sel):5.1f}% [{100 * lo:4.1f}-{100 * hi:4.1f}]")
    for lab, lo_, hi_ in (("< $5,000", 0, 5e3), (">= $5,000", 5e3, 1e18)):
        print(f"       debt {lab:9}: " + " | ".join(
            f"{n} load {100 * sum(e['lat'] >= 2 for e in s) / max(len(s), 1):4.1f}% (n={len(s)})" for n, s in
            (("low", [e for e in aave if e["load"] <= t1 and lo_ <= e["debt_usd"] < hi_]),
             ("high", [e for e in aave if e["load"] > t2 and lo_ <= e["debt_usd"] < hi_]))))
    # (b) cause: price update in the first liquidatable block, or not (interest). All delays >= 2 plus a control
    #     sample of episodes with latency <= 1.
    rng = random.Random(9)
    late = [e for e in aave if e["lat"] >= 2]
    ctrl = rng.sample([e for e in aave if e["lat"] <= 1], min(300, sum(e["lat"] <= 1 for e in aave)))
    done = {}
    if os.path.exists(CAUSE):
        done = {r["id"]: r for r in map(json.loads, open(CAUSE)) if "err" not in r}
    todo = [e for e in late + ctrl if e["id"] not in done]
    if todo:
        print(f"       measuring the cause of {len(todo)} episodes on archive nodes...", flush=True)

        def job(e):
            try:
                return price_move(e, meta)
            except Exception as ex:
                return {"id": e["id"], "err": str(ex)[:100]}
        with ThreadPoolExecutor(len(ARCHIVES) * WORKERS_PER_RPC) as ex, open(CAUSE, "a") as f:
            for r in ex.map(job, todo):
                f.write(json.dumps(r) + "\n")
                if "err" not in r:
                    done[r["id"]] = r
    print("   (b) what makes the position liquidatable in the first liquidatable block")
    for lab, sel in (("latency <= 1 (control)", ctrl), ("latency >= 2", late)):
        sel = [e for e in sel if e["id"] in done]
        k = sum(done[e["id"]]["move"] for e in sel)
        print(f"       {lab:23}: {len(sel):4} episodes, price update {100 * k / max(len(sel), 1):5.1f}%,"
              f" interest/other only {100 * (len(sel) - k) / max(len(sel), 1):5.1f}%")
    meas = [e for e in late + ctrl if e["id"] in done]
    for lab, mv in (("with a price update", True), ("without (interest/other)", False)):
        sel = [e for e in meas if done[e["id"]]["move"] == mv and e["lat"] >= 2]
        if sel:
            print(f"       delays >= 2 {lab:24}: {len(sel):4}, median latency {statistics.median(e['lat'] for e in sel):.0f} blocks,"
                  f" median debt ${statistics.median(e['debt_usd'] for e in sel):,.0f}")


# ------------------------------------------------------------------ main
def main():
    os.makedirs(DATA, exist_ok=True)
    print("1. Raw data (cached in data/)")
    cache = load_logs()
    w3 = get_w3()
    meta = load_meta(w3, cache)
    debt_tokens = {to_checksum_address("0x" + l["topics"][2][-40:]) for n in AAVE_POOLS for l in cache["logs"][n]}
    prices = load_prices(debt_tokens | {mp[0] for mp in meta["markets"].values()} | {WETH})
    evs = parse_events(cache, meta, prices)
    print(f"   blocks {cache['b0']} -> {cache['b1']}, total events {len(evs)}")

    done = {}
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            if "err" not in r:
                done[r["id"]] = r
    rng = random.Random(32)
    target = set()
    for p in PROTOS:
        ep = [e["id"] for e in evs if e["proto"] == p and e["first"] and (e.get("debt_usd") or 0) >= MIN_SIZE]
        target |= set(ep if len(ep) <= MAX_PER_PROTO else rng.sample(ep, MAX_PER_PROTO))
    todo = [e for e in evs if e["id"] in target and e["id"] not in done]
    if "--test" in sys.argv:                             # a few episodes per protocol, to check the code
        todo = [e for p in PROTOS for e in [x for x in todo if x["proto"] == p][:4]]
    print(f"2. Archive measurements: {len(todo)} episodes to measure ({len(done)} already cached)", flush=True)
    t0, errors = time.time(), Counter()
    with ThreadPoolExecutor(len(ARCHIVES) * WORKERS_PER_RPC) as ex, open(RESULTS, "a") as f:
        futs = [ex.submit(measure, e, meta, prices) for e in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            with _lock:
                f.write(json.dumps(r) + "\n")
                f.flush()
            if "err" in r:
                errors[r["err"][:60]] += 1
            else:
                done[r["id"]] = r
            if i % 200 == 0:
                print(f"   {i}/{len(todo)} in {time.time() - t0:.0f}s, errors {sum(errors.values())}", flush=True)
    if errors:
        print("   errors (rerun the script to retry):", dict(errors.most_common(5)))
    per_tx = Counter(e["tx"] for e in evs)               # one transaction can liquidate many positions:
    for e in evs:                                        # gas is split across the liquidations it contains
        r = done.get(e["id"])
        if r:
            e.update(lat=r["lat"], gross=r["gross"], gas=r["gas"] / per_tx[e["tx"]], sender=r["sender"])
            e["net"] = None if r["gross"] is None else r["gross"] - e["gas"]
            # gross bonus > 25% of debt is impossible with protocol incentives (max 15% on Morpho, ~10% on Aave):
            # the oracle does not reflect the market or the price is inconsistent, so it is left out of the economics
            if e["gross"] is not None and (e.get("debt_usd") is None or e["gross"] > 0.25 * e["debt_usd"]):
                e["gross"] = e["net"] = None
                e["odd"] = True

    # stress days: |daily ETH return| >= 5%
    eth = prices[WETH]
    stress = {d for d in eth if (p := eth.get((dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()))
              and abs(eth[d] / p - 1) >= 0.05}

    with open(CSV_OUT, "w", newline="") as f:
        cols = ["proto", "day", "block", "tx", "pair", "blue", "user", "liquidator", "sender", "first", "debt_usd", "lat",
                "gross", "gas", "net", "bad_debt_usd"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(evs)

    # ---------------- results
    print(f"\n{'=' * 100}\n3. Latency (first liquidation of each episode only, debt >= ${MIN_SIZE:,}; 12 s blocks)\n{'=' * 100}")
    print(f"   {'protocol':13} {'events':>7} {'relevant':>9} {'follow-ups':>10} {'measured':>8}  "
          + " ".join(f"{b:>7}" for b in BUCKETS) + f"  {'<=1 block [95% CI]':>22}")
    summary = {}
    for p in PROTOS:
        allp = [e for e in evs if e["proto"] == p]
        rel = [e for e in allp if (e.get("debt_usd") or 0) >= MIN_SIZE]
        m = [e for e in rel if e["first"] and "lat" in e and e["id"] in target]
        c = Counter(bucket(e["lat"]) for e in m)
        k = sum(e["lat"] <= 1 for e in m)
        lo, hi = wilson(k, len(m))
        summary[p] = m
        print(f"   {p:13} {len(allp):>7} {len(rel):>9} {sum(not e['first'] for e in rel):>10} {len(m):>8}  "
              + " ".join(f"{c[b]:>7}" for b in BUCKETS)
              + f"  {100 * k / max(len(m), 1):5.1f}% [{100 * lo:4.1f}-{100 * hi:5.1f}]")

    print("\n4. Delay >= 2 blocks by asset type and market context")
    print(f"   {'protocol':13} {'blue-chip':>22} {'exotic':>22} {'stress days':>22} {'normal days':>22}")
    for p, m in summary.items():
        def share(sel):
            n = len(sel)
            k = sum(e["lat"] >= 2 for e in sel)
            return f"{k}/{n} ({100 * k / n:4.1f}%)" if n else "-"
        print(f"   {p:13} {share([e for e in m if e['blue']]):>22} {share([e for e in m if not e['blue']]):>22}"
              f" {share([e for e in m if e['day'].isoformat() in stress]):>22}"
              f" {share([e for e in m if e['day'].isoformat() not in stress]):>22}")
    print(f"   (stress days = |daily ETH change| >= 5%: {len(stress)} days in the window)")

    print("\n5. Economics by latency bucket (Aave, Spark, Morpho; oracle prices, after gas)")
    for p in PROTOS[:4]:
        m = [e for e in summary[p] if e.get("net") is not None]
        if not m:
            continue
        gross, gas = sum(e["gross"] for e in m), sum(e["gas"] for e in m)
        print(f"   {p}: {len(m)} priced | gross bonus ${gross:,.0f} | gas ${gas:,.0f} | net ${gross - gas:,.0f}")
        for b in BUCKETS:
            sel = [e for e in m if bucket(e["lat"]) == b]
            if sel:
                bl = [e for e in sel if e["blue"]]
                print(f"      latency {b:>8}: {len(sel):5} | median net ${statistics.median(e['net'] for e in sel):>9,.0f}"
                      f" | blue-chip {len(bl):4}, blue-chip total net ${sum(e['net'] for e in bl):>10,.0f}")

    print("\n6. Blue-chip cases delayed >= 2 blocks (largest)")
    late = sorted((e for m in summary.values() for e in m if e["lat"] >= 2 and e["blue"]), key=lambda e: -(e["debt_usd"] or 0))
    for e in late[:12]:
        net = f"${e['net']:>9,.0f}" if e.get("net") is not None else "        -"
        print(f"   {e['proto']:13} {e['day']} | {e['pair']:>16} | delay {e['lat']:>5} | debt ${e['debt_usd']:>11,.0f} | net {net} | {e['tx'][:12]}…")

    print("\n7. Liquidator concentration and overlap (all relevant liquidations)")
    by_proto = {p: Counter(e["liquidator"] for e in evs if e["proto"] == p and (e.get("debt_usd") or 0) >= MIN_SIZE) for p in PROTOS}
    senders = {p: Counter(e["sender"] for e in summary[p] if e.get("sender")) for p in PROTOS}
    for p, c in by_proto.items():
        n = sum(c.values())
        if n:
            print(f"   {p:13} liquidator contracts {len(c):4} | top 3: {100 * sum(v for _, v in c.most_common(3)) / n:4.1f}%"
                  f" | sender EOAs (measured episodes) {len(senders[p]):4}")
    multi = Counter()
    for c in by_proto.values():
        multi.update(set(c))
    shared = {a for a, k in multi.items() if k >= 2}
    tot = sum(sum(c.values()) for c in by_proto.values())
    cov = sum(v for c in by_proto.values() for a, v in c.items() if a in shared)
    print(f"   contracts active on >= 2 protocols: {len(shared)}, executing {100 * cov / tot:.1f}% of all relevant liquidations")
    ms = Counter()
    for c in senders.values():
        ms.update(set(c))
    print(f"   sender EOAs active on >= 2 protocols: {sum(1 for k in ms.values() if k >= 2)}")

    print("\n8. Bad debt on Morpho Blue (loss socialised to the market's depositors)")
    bd = [e for e in evs if e["proto"] == "Morpho Blue" and e["bad_debt"]]
    for lab, sel in (("blue-chip", [e for e in bd if e["blue"]]), ("exotic", [e for e in bd if not e["blue"]])):
        usd = sum(e.get("bad_debt_usd") or 0 for e in sel)
        print(f"   {lab:9}: {len(sel):4} liquidations with bad debt, ${usd:,.0f} (priced {sum('bad_debt_usd' in e for e in sel)})")
    top = Counter()
    for e in bd:
        top[e["pair"]] += e.get("bad_debt_usd") or 0
    print("   main markets: " + ", ".join(f"{k} ${v:,.0f}" for k, v in top.most_common(5)))
    causes(evs, summary, meta)
    print(f"\nPer-event dataset: {os.path.relpath(CSV_OUT, ROOT)}")


if __name__ == "__main__":
    main()
