# PFFT Miner ⛏️

Optimized miner for **Pow Fair Free Token (PFFT)** on Ethereum Mainnet.

## Specs

- **Contract:** `0xEFAd2Eab7172dDEbE5Ce7a41f5Ddf8fCcE4Ca0CB`
- **Network:** Ethereum Mainnet
- **Wallet:** `0x69083D13C7767231EF2eAa0676F04F61b6F08a13`
- **Supply:** 21,000,000 PFFT
- **Wallet cap:** 10,000 PFFT per address
- **Gas:** Uses ETH for minting

## Files

| File | Description |
|------|-------------|
| `pfft_miner_fast.py` | Miner Python + C solver |
| `pow_solver` | Binary C PoW solver (~1.1M H/s, 2 threads) |
| `pow_solver.c` | Source code C solver |
| `mine.sh` | Launch script |

## How to Run

```bash
cd /root/BOT/PFFT
bash mine.sh
```

## Performance

| Solver | Speed | Notes |
|--------|-------|-------|
| Python only | ~25k H/s | Lambat |
| C solver | **~1.1M H/s** | **44x lebih cepat** |

> ⚠️ Difficulty 32-bit (8 hex zeros) = ~65 menit per mint dengan C solver

## Requirements

- Python 3.11+
- `requests`, `web3`, `eth-account` (pip)
- GCC (untuk compile C solver)

## Rebuild C Solver

```bash
gcc -O2 -march=native -fopenmp -o pow_solver pow_solver.c -lm
```

## Notes

- Mining butuh ETH untuk gas fee
- Max 10,000 PFFT per wallet
- Nonce-based PoW: cari hash dengan N leading zero hex digits
- Telegram notifikasi saat mint berhasil (opsional)

---

*Last updated: 2026-05-12*
