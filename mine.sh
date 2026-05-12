#!/bin/bash
export PYTHONUNBUFFERED=1
cd /root/BOT/PFFT

echo "⛏️  PFFT Miner Starting..."
echo "   Script: pfft_miner_fast.py (C solver + gas cap \$0.1)"
echo "=================================="

python3 -u pfft_miner_fast.py
