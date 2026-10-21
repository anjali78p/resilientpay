#!/usr/bin/env bash
# Quick API test: 2 accounts, transfer, duplicate transfer (idempotency), balance check
B=${1:-http://localhost}
J='Content-Type: application/json'
id() { python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'; }
A=$(curl -s -X POST $B/accounts -H "$J" -d '{"name":"Asha","balance":1000}' | id)
C=$(curl -s -X POST $B/accounts -H "$J" -d '{"name":"Ravi","balance":500}'  | id)
echo "accounts: $A $C"
echo "transfer 1:"; curl -s -X POST $B/transfer -H "$J" -d "{\"from_id\":$A,\"to_id\":$C,\"amount\":200,\"idempotency_key\":\"k-$A-$C\"}"; echo
echo "same key again (must be ignored):"; curl -s -X POST $B/transfer -H "$J" -d "{\"from_id\":$A,\"to_id\":$C,\"amount\":200,\"idempotency_key\":\"k-$A-$C\"}"; echo
echo "balances (expect 800 / 700):"; curl -s $B/balance/$A; echo; curl -s $B/balance/$C; echo
