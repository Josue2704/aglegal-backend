from pydantic import BaseModel, ConfigDict


class AttachmentOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    original_name: str
    stored_path: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)
