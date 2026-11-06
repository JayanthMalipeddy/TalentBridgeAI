from pathlib import Path
from sqlalchemy import create_engine, event, MetaData, Table, Column, String, Text, Float

metadata = MetaData()
records = Table("records", metadata, Column("kind", String, primary_key=True),
                Column("id", String, primary_key=True), Column("payload", Text, nullable=False))
usage = Table("usage", metadata, Column("id", String, primary_key=True),
              Column("provider", String, nullable=False), Column("unit", String, nullable=False),
              Column("amount", Float, nullable=False), Column("state", String, nullable=False),
              Column("details", Text, nullable=False))


def make_engine(url):
    if not url.startswith("sqlite:"):
        raise ValueError("This prototype requires SQLite")
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
    metadata.create_all(engine)
    return engine
