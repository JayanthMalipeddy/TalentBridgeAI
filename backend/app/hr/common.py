from datetime import datetime,timezone
from hashlib import sha256
import json
from ..errors import AppError

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def maybe(repo,conn,kind,key,default=None):
    try:return repo._get(conn,kind,key)
    except AppError as e:
        if e.code!='NOT_FOUND':raise
        return default

def all_rows(repo,conn,kind):
    from sqlalchemy import select
    from ..db import records
    return [json.loads(r) for r in conn.execute(select(records.c.payload).where(records.c.kind==kind)).scalars()]
