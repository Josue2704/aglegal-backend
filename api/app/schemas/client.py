from pydantic import BaseModel, ConfigDict


class ClientIn(BaseModel):
    name: str
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""


class ClientOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    created_at: str
    session_count: int = 0
    case_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class HistoryItem(BaseModel):
    date: str | None = None
    type: str
    detail: str | None = None
    status: str | None = None
