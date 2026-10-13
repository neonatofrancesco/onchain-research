"""
Shared helpers: public Ethereum RPC endpoints with fallback, and the Blockscout API with explicit status checks.

Free public RPCs change often (rate limits, closed endpoints, keys becoming mandatory). If one stops working,
update the list below or set your own endpoint in .env as ETH_RPC, which takes precedence.
"""

import os
import time

import requests
from dotenv import load_dotenv
from web3 import Web3
from web3.providers.rpc.utils import ExceptionRetryConfiguration

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")          # caches and outputs (not versioned)
load_dotenv(os.path.join(ROOT, ".env"))

# Endpoints checked on 2026-10-13; the first one that answers wins.
RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://eth-mainnet.public.blastapi.io"]

# Blockscout: a free API key works only on the PRO API, with an explicit chain_id.
BLOCKSCOUT_PUBLIC = "https://eth.blockscout.com/api"
BLOCKSCOUT_PRO = "https://api.blockscout.com/v2/api"


def make_w3(url, timeout=15, retry=True):
    """Web3 over HTTP. With retry=True, read calls are retried with growing waits on HTTP and network errors
    (e.g. 429 Too Many Requests from free RPCs)."""
    kwargs = {}
    if retry:
        kwargs["exception_retry_configuration"] = ExceptionRetryConfiguration(
            errors=(requests.ConnectionError, requests.HTTPError, requests.Timeout), retries=5, backoff_factor=0.5)
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}, **kwargs))


def get_w3():
    """Web3 connected to the first working Ethereum mainnet RPC."""
    urls = ([os.getenv("ETH_RPC")] if os.getenv("ETH_RPC") else []) + RPCS
    errors = []
    for url in urls:
        try:
            w3 = make_w3(url)
            if w3.eth.chain_id == 1:
                return w3
            errors.append(f"{url}: unexpected chain_id")
        except Exception as e:  # network down, rate limit, non-JSON answer...
            errors.append(f"{url}: {type(e).__name__}")
    raise ConnectionError("No working Ethereum RPC:\n  " + "\n  ".join(errors))


def blockscout_get(params, retries=6):
    """Blockscout API call with status checks. CAUTION: when rate-limited the API can answer status "0" with an
    EMPTY result. Without this check an error is silently mistaken for "no events" and the dataset becomes
    incomplete."""
    url = BLOCKSCOUT_PUBLIC
    if os.getenv("BLOCKSCOUT_API_KEY"):
        url = BLOCKSCOUT_PRO
        params = {**params, "chain_id": 1, "apikey": os.getenv("BLOCKSCOUT_API_KEY")}
    wait, msg = 5, ""
    for _ in range(retries):
        r = requests.get(url, params=params, timeout=60).json()
        if r.get("error") and "too many" in str(r["error"]).lower():   # rate limit: wait and retry
            time.sleep(wait)
            wait *= 2
            continue
        if r.get("error"):          # plan or permission error: retrying is pointless
            raise RuntimeError(f"Blockscout refused the request: {r['error']}")
        msg = str(r.get("message", ""))
        if r.get("status") == "1":
            return r["result"]
        if "no logs" in msg.lower() or "no records" in msg.lower():
            return []               # genuinely no results
        time.sleep(wait)            # rate limit or transient error
        wait *= 2
    raise RuntimeError(f"Blockscout is not answering correctly ({msg}): data would be incomplete, stopping.")


def blockscout_logs(address, topic0, from_block, to_block, step=100_000):
    """All logs (address, topic0) in the range. Windows that hit the 1,000-result API cap are split in two.
    Returns (logs, number of HTTP calls)."""
    def window(b, e):
        res = blockscout_get({"module": "logs", "action": "getLogs", "fromBlock": b, "toBlock": e,
                              "address": address, "topic0": topic0})
        if len(res) >= 1000 and e > b:
            mid = (b + e) // 2
            left, right = window(b, mid), window(mid + 1, e)
            return left[0] + right[0], 1 + left[1] + right[1]
        return res, 1
    out, calls, b = [], 0, from_block
    while b <= to_block:
        e = min(b + step - 1, to_block)
        res, c = window(b, e)
        out += res
        calls += c
        b = e + 1
    return out, calls
