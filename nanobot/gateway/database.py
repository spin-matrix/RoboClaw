from typing import Annotated
from fastapi import Depends
from sqlmodel import SQLModel, Session, create_engine
from nanobot.config.paths import get_data_dir

sqlite_file_name = 'nanobot.db'
sqlite_file_path = get_data_dir() / sqlite_file_name
sqlite_url = f'sqlite:///{sqlite_file_path}'

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

SessionDep = Annotated[Session, Depends(get_session)]
