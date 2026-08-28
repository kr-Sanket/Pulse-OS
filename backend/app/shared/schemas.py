"""Shared API schema base: JSON is camelCase on the wire (docs/API_GUIDELINES.md),
snake_case in Python. Every module's request/response models extend ``ApiModel``.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class RequestModel(ApiModel):
    """Base for request bodies: unknown fields are rejected on writes (API_GUIDELINES)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
