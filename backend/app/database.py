import unicodedata
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from app.config import settings

db_url = settings.DATABASE_URL
connect_args = {}

if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()


def trigram_sim(s1: str, s2: str) -> float:
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower(), s2.lower()
    if s1 == s2:
        return 1.0
    if len(s1) < 3 or len(s2) < 3:
        return 1.0 if (s1 in s2 or s2 in s1) else 0.0
    t1 = set(s1[i:i+3] for i in range(len(s1) - 2))
    t2 = set(s2[i:i+3] for i in range(len(s2) - 2))
    intersection = t1.intersection(t2)
    union = t1.union(t2)
    return len(intersection) / len(union) if union else 0.0


def unaccent_text(text: str) -> str:
    if not text:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


@event.listens_for(engine, "connect")
def on_connect(dbapi_connection, connection_record):
    if db_url.startswith("sqlite"):
        try:
            dbapi_connection.create_function("similarity", 2, trigram_sim)
            dbapi_connection.create_function("unaccent", 1, unaccent_text)
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
