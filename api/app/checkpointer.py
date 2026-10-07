from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.settings import settings

@lru_cache  
def get_checkpointer() -> PostgresSaver:
    pool = ConnectionPool(
        
        conninfo=settings.database_url.replace(
            "postgresql+psycopg://", "postgresql://"
        ),
        max_size=5,
        
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
        },
        open=True,
    )

    checkpointer = PostgresSaver(pool)
    checkpointer.setup()  
    return checkpointer