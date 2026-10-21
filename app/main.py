import json, logging, os, time, uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel, Field

DB_URL = os.getenv("DATABASE_URL", "postgresql://bank:bank@db:5432/bank")
START = time.time()

# ---- structured JSON logs (CloudWatch Logs me easily searchable) ----
logger = logging.getLogger("resilientpay")
logger.setLevel(logging.INFO)
_h = logging.StreamHandler()
_h.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_h)

def log(event, **kw):
    logger.info(json.dumps({"event": event, "ts": time.time(), **kw}, default=str))

# ---- DB pool ----
pool = None

def get_pool():
    global pool
    if pool is None:
        pool = ThreadedConnectionPool(1, 10, DB_URL, connect_timeout=3)
    return pool

@contextmanager
def tx():
    """One atomic DB transaction: commit on success, rollback on any error."""
    p = get_pool()
    conn = p.getconn()
    try:
        with conn:                      # commit / rollback
            with conn.cursor() as cur:
                yield cur
    except Exception:
        p.putconn(conn, close=conn.closed != 0)   # broken connection pool se hatao
        raise
    else:
        p.putconn(conn)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  balance NUMERIC(14,2) NOT NULL CHECK (balance >= 0)
);
CREATE TABLE IF NOT EXISTS transfers (
  id SERIAL PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  from_id INT NOT NULL REFERENCES accounts(id),
  to_id INT NOT NULL REFERENCES accounts(id),
  amount NUMERIC(14,2) NOT NULL CHECK (amount > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def init_db(retries=30):
    for i in range(retries):
        try:
            with tx() as cur:
                cur.execute(SCHEMA)
            log("db_ready")
            return
        except Exception as e:
            log("db_wait", attempt=i + 1, error=str(e)[:100])
            time.sleep(1)
    raise RuntimeError("database not reachable")

app = FastAPI(title="ResilientPay")
init_db()

@app.middleware("http")
async def access_log(request: Request, call_next):
    t = time.time()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        if request.url.path != "/health":
            log("request", method=request.method, path=request.url.path,
                status=status, latency_ms=round((time.time() - t) * 1000, 1))

class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    balance: Decimal = Field(default=Decimal("0"), ge=0)

class TransferIn(BaseModel):
    from_id: int
    to_id: int
    amount: Decimal = Field(gt=0)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

@app.get("/health")
def health():
    try:
        with tx() as cur:
            cur.execute("SELECT 1")
        return {"status": "ok", "db": "up", "uptime_s": round(time.time() - START, 1)}
    except Exception:
        return JSONResponse({"status": "down", "db": "down"}, status_code=503)

@app.post("/accounts", status_code=201)
def create_account(a: AccountIn):
    with tx() as cur:
        cur.execute("INSERT INTO accounts(name, balance) VALUES (%s,%s) RETURNING id",
                    (a.name, a.balance))
        return {"id": cur.fetchone()[0], "name": a.name, "balance": a.balance}

@app.get("/accounts")
def list_accounts():
    with tx() as cur:
        cur.execute("SELECT id, name, balance FROM accounts ORDER BY id")
        return [{"id": r[0], "name": r[1], "balance": r[2]} for r in cur.fetchall()]

@app.get("/balance/{account_id}")
def balance(account_id: int):
    with tx() as cur:
        cur.execute("SELECT id, name, balance FROM accounts WHERE id=%s", (account_id,))
        r = cur.fetchone()
    if not r:
        raise HTTPException(404, "account not found")
    return {"id": r[0], "name": r[1], "balance": r[2]}

@app.post("/transfer")
def transfer(t: TransferIn):
    if t.from_id == t.to_id:
        raise HTTPException(400, "cannot transfer to same account")
    with tx() as cur:
        # idempotency: same key dobara aaye to paisa dobara nahi katega
        cur.execute("SELECT id FROM transfers WHERE idempotency_key=%s", (t.idempotency_key,))
        if cur.fetchone():
            return {"status": "duplicate_ignored", "idempotency_key": t.idempotency_key}
        # fixed order me lock => deadlock nahi
        cur.execute("SELECT id, balance FROM accounts WHERE id IN (%s,%s) ORDER BY id FOR UPDATE",
                    (t.from_id, t.to_id))
        rows = {r[0]: r[1] for r in cur.fetchall()}
        if t.from_id not in rows or t.to_id not in rows:
            raise HTTPException(404, "account not found")
        if rows[t.from_id] < t.amount:
            raise HTTPException(422, "insufficient funds")
        # debit + credit + record: ek hi transaction (atomic)
        cur.execute("UPDATE accounts SET balance=balance-%s WHERE id=%s", (t.amount, t.from_id))
        cur.execute("UPDATE accounts SET balance=balance+%s WHERE id=%s", (t.amount, t.to_id))
        cur.execute("INSERT INTO transfers(idempotency_key,from_id,to_id,amount) VALUES (%s,%s,%s,%s)",
                    (t.idempotency_key, t.from_id, t.to_id, t.amount))
    log("transfer_ok", from_id=t.from_id, to_id=t.to_id, amount=t.amount)
    return {"status": "success", "idempotency_key": t.idempotency_key}

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
