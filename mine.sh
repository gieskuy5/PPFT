#!/bin/bash
export PYTHONUNBUFFERED=1
cd /root/BOT/PFFT

echo "⛏️  PFFT Miner Starting..."
echo "   Solver: C (2 threads)"
echo "   Wallet: 0x69083D13C7767231EF2eAa0676F04F61b6F08a13"
echo "=================================="

python3 -u -c "
import os, sys, time
from pathlib import Path
from web3 import Web3
from eth_account import Account
import subprocess

_env_path = Path('.') / '.env'
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())

CONTRACT = '0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB'
RPC = os.environ.get('ETH_RPC', 'https://ethereum-rpc.publicnode.com')
PK = os.environ.get('PRIVATE_KEY', '')
SOLVER = './pow_solver'

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={'timeout': 30}))
wallet = Account.from_key(PK)
print(f'✅ Connected | Block #{w3.eth.block_number} | Wallet: {wallet.address}')
sys.stdout.flush()

eth_bal = w3.eth.get_balance(wallet.address) / 1e18
print(f'💰 ETH: {eth_bal:.6f}')
sys.stdout.flush()

ABI = [
    {'inputs':[],'name':'currentPowHexZeros','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'totalMinted','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'MAX_SUPPLY','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'requested','type':'uint256'}],'name':'calculateActualMint','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'user','type':'address'}],'name':'currentPowChallenge','outputs':[{'type':'bytes32'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'user','type':'address'},{'name':'powNonce','type':'uint256'}],'name':'isValidPow','outputs':[{'type':'bool'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'powNonce','type':'uint256'}],'name':'freeMint','outputs':[],'stateMutability':'nonpayable','type':'function'},
    {'inputs':[{'name':'user','type':'address'}],'name':'mintedByAddress','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'account','type':'address'}],'name':'balanceOf','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},
]
contract = w3.eth.contract(address=w3.to_checksum_address(CONTRACT), abi=ABI)

round_num = 0
total_minted_count = 0
total_pfft = 0
start_time = time.time()

while True:
    round_num += 1
    print(f'\n--- Round #{round_num} ---')
    sys.stdout.flush()

    hex_zeros = contract.functions.currentPowHexZeros().call()
    total_minted = contract.functions.totalMinted().call()
    max_supply = contract.functions.MAX_SUPPLY().call()
    next_mint = contract.functions.calculateActualMint(w3.to_wei(1000, 'ether')).call()
    wallet_minted = contract.functions.mintedByAddress(wallet.address).call()
    wallet_bal = contract.functions.balanceOf(wallet.address).call()
    target = (2**256 - 1) >> (hex_zeros * 4)
    progress = total_minted * 10000 / max_supply / 100

    print(f'Supply: {total_minted/1e18:,.0f}/{max_supply/1e18:,.0f} ({progress:.1f}%) | Next: ~{next_mint/1e18:,.2f} PFFT | Diff: {hex_zeros*4}-bit')
    print(f'Wallet: {wallet_minted/1e18:,.2f} minted | {wallet_bal/1e18:,.2f} PFFT balance')
    sys.stdout.flush()

    if total_minted >= max_supply:
        print('🏁 Max supply reached!')
        break
    if wallet_minted >= 10_000 * 1e18:
        print('🏁 Wallet cap reached!')
        break

    challenge = contract.functions.currentPowChallenge(wallet.address).call()
    if isinstance(challenge, int):
        challenge = challenge.to_bytes(32, 'big')
    challenge_hex = challenge.hex()
    target_hex = target.to_bytes(32, 'big').hex()

    print(f'Mining {hex_zeros*4}-bit...')
    sys.stdout.flush()

    t0 = time.time()
    result = subprocess.run([SOLVER, challenge_hex, target_hex, '2'], capture_output=True, text=True, timeout=900)

    if result.returncode == 0 and result.stdout.strip():
        nonce = int(result.stdout.strip())
        elapsed = time.time() - t0
        print(f'FOUND nonce={nonce} in {elapsed:.0f}s')
        sys.stdout.flush()

        is_valid = contract.functions.isValidPow(wallet.address, nonce).call()
        if not is_valid:
            print('Invalid nonce, re-mining...')
            continue

        fn = contract.functions.freeMint(nonce)
        tx = fn.build_transaction({
            'from': wallet.address,
            'nonce': w3.eth.get_transaction_count(wallet.address),
            'chainId': 1,
            'gas': 200000,
        })
        tx['gasPrice'] = w3.eth.gas_price
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f'TX: https://etherscan.io/tx/0x{tx_hash.hex()}')
        sys.stdout.flush()

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status == 1:
            earned = next_mint / 1e18
            total_minted_count += 1
            total_pfft += earned
            print(f'MINT OK! +{earned:,.2f} PFFT | Total: {total_pfft:,.2f} PFFT')
        else:
            print(f'REVERTED | Gas {receipt.gasUsed}')
    else:
        print(f'Solver failed: {result.stderr[:200]}')

    elapsed_total = (time.time() - start_time) / 60
    print(f'Session: {total_minted_count} mints | {total_pfft:,.2f} PFFT | {elapsed_total:.1f} min')
    sys.stdout.flush()
    time.sleep(3)
"
