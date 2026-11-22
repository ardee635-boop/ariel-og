"""
Database facade. Table groups live next to the code that uses them:
  core/db_core.py      connection + player store + meta + table creation
  pokemon/db_pokemon.py, rpg/db_rpg.py, chat/db_chat.py
Callers keep using `from database import Database`.
"""
from db_core import DbCore
from db_pokemon import PokemonDb
from db_rpg import RpgDb
from db_chat import ChatDb


class Database(DbCore, PokemonDb, RpgDb, ChatDb):
    pass
