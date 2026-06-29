from typing import Optional
from sqlmodel import SQLModel, Field

class Strategy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    enabled: bool = True
    params: Optional[str] = None
