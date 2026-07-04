from pydantic import BaseModel, ConfigDict


CLIENT_TYPES = ["Física", "Jurídica"]


class ClientIn(BaseModel):
    name: str
    client_type: str = "Física"
    id_number: str = ""
    phone: str = ""
    phone2: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""


class ClientOut(BaseModel):
    id: int
    name: str
    client_type: str = "Física"
    id_number: str | None = None
    phone: str | None = None
    phone2: str | None = None
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
