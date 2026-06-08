import os
from db_manager.manager import DBManager
from dotenv import load_dotenv

load_dotenv()
conn_url = os.getenv("DATABASE_URL")
assert conn_url is not None
db = DBManager(conn_url)
