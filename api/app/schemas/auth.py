from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    role_id: int | None = None
    is_admin: bool = False
    permissions: list[str] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserInfo
