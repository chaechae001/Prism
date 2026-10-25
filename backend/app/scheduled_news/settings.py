"""Strict, non-secret settings. Parsing configuration has no external effects."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..cluster_store.bundle import USES, load_json

Permission = Literal['allowed','unknown','denied']


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    key: Literal['khan','sbs','mk']
    enabled: bool = False
    categories: list[Literal['economy','politics']] = Field(default_factory=lambda:['economy'],min_length=1,max_length=2)

    @field_validator('categories')
    @classmethod
    def unique_categories(cls,value):
        if len(value)!=len(set(value)):raise ValueError('Duplicate feed category')
        return value
    rights: dict[str,Permission] = Field(default_factory=lambda:{use:'unknown' for use in USES})

    @field_validator('rights')
    @classmethod
    def complete_rights(cls,value):
        if set(value)!=set(USES):raise ValueError('Every source needs five explicit rights scopes')
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    namespace: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    interval_seconds: int = Field(default=900,ge=60,le=86400)
    window_hours: int = Field(default=72,ge=1,le=168)
    max_articles: int = Field(default=500,ge=1,le=500)
    refetch_seconds: int = Field(default=21600,ge=300,le=86400)
    limit_per_feed: int = Field(default=20,ge=1,le=100)
    min_body_characters: int = Field(default=200,ge=1,le=10000)
    profile: Literal['v2','multiview','multiview-dev','multiview-group','multiview-anchor'] = 'multiview-anchor'
    analysis_revision: str = Field(default='scheduled-v1',pattern=r'^[A-Za-z0-9_.-]{1,80}$')
    usage_scope: Literal['local_test'] = 'local_test'
    model_dir: Path
    work_dir: Path
    sources: list[SourcePolicy] = Field(min_length=1,max_length=3)

    @field_validator('model_dir','work_dir',mode='before')
    @classmethod
    def paths(cls,value):
        if not isinstance(value,(str,Path)) or not str(value).strip():raise ValueError('Expected local path')
        return Path(value).resolve()

    @model_validator(mode='after')
    def no_duplicate_sources(self):
        if len({s.key for s in self.sources})!=len(self.sources):raise ValueError('Duplicate source key')
        return self

    @property
    def active_sources(self):
        return [s for s in self.sources if s.enabled and s.rights['collect']=='allowed' and s.rights['store']=='allowed']

    def check(self):
        return dict(namespace=self.namespace,interval_seconds=self.interval_seconds,
            active_sources=[s.key for s in self.active_sources],
            blocked_sources=[s.key for s in self.sources if s.enabled and s not in self.active_sources],
            local_model_ready=all((self.model_dir/f).is_file() for f in ('tokenizer.json','onnx/model_quantized.onnx')),
            database_writes=0,llm_calls=0)


def load_settings(path):
    path=Path(path).resolve()
    raw=load_json(path.read_bytes())
    if not isinstance(raw,dict):raise ValueError('Expected settings object')
    for key in ('model_dir','work_dir'):
        if isinstance(raw.get(key),str) and not Path(raw[key]).is_absolute():
            raw[key]=str(path.parent/raw[key])
    return Settings.model_validate(raw)
