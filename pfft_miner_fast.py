#!/usr/bin/env python3
"""
PFFT Miner Bot — Optimized (C PoW solver + Python orchestration)
Ethereum Mainnet | Contract: 0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB

Usage:
  cp .env.example .env   # then set PRIVATE_KEY
  python3 pfft_miner_fast.py
"""

import os
import sys
import time
import signal
import subprocess
import shutil
from pathlib import Path

# Load .env
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONTRACT = "0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB"
CHAIN_ID = 1
RPC = os.environ.get("ETH_RPC", "https://ethereum-rpc.publicnode.com")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
GAS_LIMIT = 200000
PAUSE_BETWEEN_ROUNDS = 5
SOLVER_PATH = str(Path(__file__).parent / "pow_solver")
NUM_THREADS = os.cpu_count() or 2

# ---------------------------------------------------------------------------
# C Solver wrapper
# ---------------------------------------------------------------------------
def solve_pow_c(challenge_bytes: bytes, target_bytes: bytes) -> tuple:
    """Call C solver. Returns (nonce, None) or (None, None)."""
    challenge_hex = challenge_bytes.hex()
    target_hex = target_bytes.hex()

    try:
        result = subprocess.run(
            [SOLVER_PATH, challenge_hex, target_hex, str(NUM_THREADS)],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0 and result.stdout.strip():
            nonce = int(result.stdout.strip())
            return nonce, None
        else:
            print(f"  ❌ C solver error: {result.stderr[:200]}")
            return None, None
    except subprocess.TimeoutExpired:
        print("  ⏰ Solver timeout (10min)")
        return None, None
    except Exception as e:
        print(f"  ❌ Solver exception: {e}")
        return None, None

# ---------------------------------------------------------------------------
# Fallback: Python PoW solver
# ---------------------------------------------------------------------------
def solve_pow_python(challenge: bytes, target: int) -> tuple:
    """Fallback Python solver."""
    try:
        from Crypto.Hash import keccak as _keccak_mod
    except ImportError:
        print("  ❌ pycryptodome not installed")
        return None, None

    import struct
    nonce = 0
    start = time.time()
    buf = bytearray(challenge) + bytearray(32)

    while True:
        struct.pack_into('>QQQQ', buf, 32, 0, 0, 0, nonce)
        h = _keccak_mod.new(digest_bits=256, data=bytes(buf)).digest()
        h_int = int.from_bytes(h, 'big')

        if h_int <= target:
            elapsed = time.time() - start
            rate = nonce / elapsed if elapsed > 0 else 0
            print(f"\n  ✅ Python solver: nonce={nonce} | {elapsed:.1f}s | {rate:,.0f} H/s")
            return nonce, h

        nonce += 1
        if nonce % 50000 == 0:
            elapsed = time.time() - start
            rate = nonce / elapsed if elapsed > 0 else 0
            print(f"  ⛏️  {nonce:,} attempts | {rate:,.0f} H/s | {elapsed:.0f}s", end='\r')

# ---------------------------------------------------------------------------
# Contract interaction
# ---------------------------------------------------------------------------
def load_contract(w3):
    ABI = [
        {"inputs":[],"name":"currentPowHexZeros","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"totalMinted","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"MAX_SUPPLY","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"requested","type":"uint256"}],"name":"calculateActualMint","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"user","type":"address"}],"name":"currentPowChallenge","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"user","type":"address"},{"name":"powNonce","type":"uint256"}],"name":"isValidPow","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"powNonce","type":"uint256"}],"name":"freeMint","outputs":[],"stateMutability":"nonpayable","type":"function"},
        {"inputs":[{"name":"user","type":"address"}],"name":"mintedByAddress","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[],"name":"getInfo","outputs":[{"type":"uint256"},{"type":"uint256"},{"type":"uint256"},{"type":"uint256"}],"stateMutability":"view","type":"function"},
        {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    ]
    return w3.eth.contract(address=w3.to_checksum_address(CONTRACT), abi=ABI)


def get_status(contract, wallet_addr, w3):
    hex_zeros = contract.functions.currentPowHexZeros().call()
    total_minted = contract.functions.totalMinted().call()
    max_supply = contract.functions.MAX_SUPPLY().call()
    next_mint = contract.functions.calculateActualMint(w3.to_wei(1000, 'ether')).call()
    wallet_minted = contract.functions.mintedByAddress(wallet_addr).call()
    wallet_bal = contract.functions.balanceOf(wallet_addr).call()
    target = (2**256 - 1) >> (hex_zeros * 4)
    progress = total_minted * 10000 / max_supply / 100

    return {
        "hex_zeros": hex_zeros,
        "difficulty_bits": hex_zeros * 4,
        "total_minted": total_minted,
        "max_supply": max_supply,
        "next_mint": next_mint,
        "wallet_minted": wallet_minted,
        "wallet_bal": wallet_bal,
        "target": target,
        "target_bytes": target.to_bytes(32, 'big'),
        "progress": progress,
    }


def get_challenge(contract, wallet_addr):
    c = contract.functions.currentPowChallenge(wallet_addr).call()
    return c if isinstance(c, bytes) else c.to_bytes(32, 'big')


def fetch_eth_price():
    """Fetch ETH price in USD."""
    import urllib.request, json as _json
    try:
        r = urllib.request.urlopen(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
            timeout=10
        )
        return _json.loads(r.read())["ethereum"]["usd"]
    except Exception:
        return None


def submit_mint(w3, wallet, contract, nonce):
    try:
        fn = contract.functions.freeMint(nonce)

        # EIP-1559: cap total gas cost at $0.1
        MAX_GAS_USD = 0.1
        eth_price = fetch_eth_price()

        # Estimate gas
        try:
            estimated_gas = fn.estimate_gas({'from': wallet.address})
            estimated_gas = int(estimated_gas * 1.2)  # buffer 20%
        except Exception:
            estimated_gas = GAS_LIMIT

        tx_params = {
            'from': wallet.address,
            'nonce': w3.eth.get_transaction_count(wallet.address),
            'chainId': CHAIN_ID,
            'gas': min(estimated_gas, GAS_LIMIT),
        }

        latest_block = w3.eth.get_block('latest')
        base_fee = latest_block.get('baseFeePerGas', None)

        if eth_price and eth_price > 0:
            max_cost_eth = MAX_GAS_USD / eth_price
            max_gas_price = max_cost_eth / tx_params['gas']
            max_gas_gwei = w3.from_wei(int(max_gas_price), 'gwei')
        else:
            # Fallback: 0.5 Gwei
            max_gas_price = w3.to_wei(0.5, 'gwei')
            max_gas_gwei = 0.5

        if base_fee is not None:
            priority_fee = w3.to_wei(0.01, 'gwei')
            max_fee = int(max_gas_price)

            if max_fee < base_fee:
                # Gas market terlalu tinggi, set rendah dan tunggu
                print(f"  ⛽ Base fee ({w3.from_wei(base_fee, 'gwei'):.2f}) > budget $0.1")
                print(f"  ⛽ Max gas: {max_gas_gwei:.4f} Gwei — TX akan pending sampai gas turun")
            else:
                print(f"  ⛽ Gas: base={w3.from_wei(base_fee, 'gwei'):.2f} | "
                      f"max={max_gas_gwei:.4f} Gwei | Budget: $0.1")

            tx_params['maxPriorityFeePerGas'] = priority_fee
            tx_params['maxFeePerGas'] = max_fee
            tx_params['type'] = 2
        else:
            gas_price = int(min(w3.eth.gas_price, max_gas_price))
            tx_params['gasPrice'] = gas_price
            print(f"  ⛽ Gas: {w3.from_wei(gas_price, 'gwei'):.4f} Gwei | Budget: $0.1")

        # Cost estimate
        if eth_price:
            est_cost_eth = tx_params.get('maxFeePerGas', tx_params.get('gasPrice', 0)) * tx_params['gas']
            est_cost_usd = est_cost_eth / 1e18 * eth_price
            print(f"  💵 Est cost: ~${est_cost_usd:.4f} (ETH ${eth_price:,.0f})")

        tx = fn.build_transaction(tx_params)
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  📤 TX: https://etherscan.io/tx/0x{tx_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            print(f"  ✅ MINT OK | Block {receipt.blockNumber} | Gas {receipt.gasUsed}")
            return True
        else:
            print(f"  ❌ REVERTED | Gas {receipt.gasUsed}")
            return False
    except Exception as e:
        print(f"  ❌ TX error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
running = True
def handle_signal(sig, frame):
    global running
    print("\n  ⚠️  Stopping miner...")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def main():
    from web3 import Web3
    from eth_account import Account

    # Check C solver
    use_c_solver = os.path.exists(SOLVER_PATH) and os.access(SOLVER_PATH, os.X_OK)
    solver_name = f"C solver ({NUM_THREADS} threads)" if use_c_solver else "Python fallback"

    print("=" * 60)
    print("  ⛏️  PFFT Miner Bot — Optimized")
    print(f"  Contract: {CONTRACT}")
    print(f"  RPC: {RPC}")
    print(f"  Solver: {solver_name}")
    print("=" * 60)

    # Connect
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        print("❌ Cannot connect to RPC")
        sys.exit(1)
    print(f"✅ Connected | Block #{w3.eth.block_number}")

    # Load wallet
    pk = PRIVATE_KEY.strip()
    if not pk or pk == "your_private_key_here":
        print("❌ PRIVATE_KEY not set!")
        sys.exit(1)
    if not pk.startswith('0x'):
        pk = '0x' + pk
    wallet = Account.from_key(pk)
    print(f"✅ Wallet: {wallet.address}")

    # ETH balance
    eth_bal = w3.eth.get_balance(wallet.address) / 1e18
    print(f"💰 ETH: {eth_bal:.6f}")
    if eth_bal < 0.00005:
        print("⚠️  Low ETH! Need ~0.00005+ ETH for gas")

    # Contract
    contract = load_contract(w3)
    s = get_status(contract, wallet.address, w3)
    print(f"\n📊 Contract:")
    print(f"   Minted: {s['total_minted']/1e18:,.0f} / {s['max_supply']/1e18:,.0f} PFFT ({s['progress']:.1f}%)")
    print(f"   Next mint: ~{s['next_mint']/1e18:,.2f} PFFT")
    print(f"   Difficulty: {s['hex_zeros']} hex zeros ({s['difficulty_bits']}-bit)")
    print(f"   Wallet minted: {s['wallet_minted']/1e18:,.2f} / 10,000 PFFT")
    print(f"   Wallet balance: {s['wallet_bal']/1e18:,.2f} PFFT")

    # Mining loop
    round_num = 0
    total_minted_count = 0
    total_pfft_earned = 0
    global_start = time.time()

    while running:
        round_num += 1
        print(f"\n{'─'*60}")
        print(f"  Round #{round_num}")
        print(f"{'─'*60}")

        # Refresh status
        try:
            s = get_status(contract, wallet.address, w3)
            print(f"  Supply: {s['total_minted']/1e18:,.0f} ({s['progress']:.1f}%) | "
                  f"Next: ~{s['next_mint']/1e18:,.2f} PFFT | "
                  f"Diff: {s['difficulty_bits']}-bit")

            if s['total_minted'] >= s['max_supply']:
                print("  🏁 Max supply reached!")
                break
            if s['wallet_minted'] >= 10_000 * 1e18:
                print("  🏁 Wallet cap (10,000 PFFT) reached!")
                break
        except Exception as e:
            print(f"  ⚠️  Status error: {e}, retrying in 15s...")
            time.sleep(15)
            continue

        # Get challenge
        challenge = get_challenge(contract, wallet.address)

        # Solve PoW
        print(f"  ⛏️  Mining ({s['difficulty_bits']}-bit) with {solver_name}...")
        t0 = time.time()

        if use_c_solver:
            nonce, h = solve_pow_c(challenge, s['target_bytes'])
        else:
            nonce, h = solve_pow_python(challenge, s['target'])

        if nonce is None:
            print("  Failed, retrying...")
            continue

        mining_time = time.time() - t0
        print(f"  ⏱️  Mining took {mining_time:.1f}s")

        # Verify before submitting
        try:
            is_valid = contract.functions.isValidPow(wallet.address, nonce).call()
            if not is_valid:
                print("  ⚠️  Nonce invalid on-chain (supply changed?), re-mining...")
                continue
        except Exception as e:
            print(f"  ⚠️  Verify error: {e}, submitting anyway...")

        # Submit mint
        success = submit_mint(w3, wallet, contract, nonce)
        if success:
            total_minted_count += 1
            earned = s['next_mint'] / 1e18
            total_pfft_earned += earned
            print(f"  💰 +{earned:,.2f} PFFT | Total: {total_pfft_earned:,.2f} PFFT from {total_minted_count} mints")

            # Check new balance
            try:
                bal = contract.functions.balanceOf(wallet.address).call()
                print(f"  💰 PFFT balance: {bal/1e18:,.2f}")
            except:
                pass

        # Summary
        elapsed = time.time() - global_start
        print(f"\n  📈 Session: {total_minted_count} mints | {total_pfft_earned:,.2f} PFFT | {elapsed/60:.1f} min")

        # Pause
        if running:
            print(f"  ⏳ {PAUSE_BETWEEN_ROUNDS}s cooldown...")
            time.sleep(PAUSE_BETWEEN_ROUNDS)

    print(f"\n{'='*60}")
    print(f"  Session Summary")
    print(f"  Mints: {total_minted_count}")
    print(f"  PFFT earned: {total_pfft_earned:,.2f}")
    print(f"  Runtime: {(time.time()-global_start)/60:.1f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
