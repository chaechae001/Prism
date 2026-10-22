import json
from pathlib import Path
from typing import Protocol
from .models import Story

ROOT = Path(__file__).resolve().parents[2]

class StoryRepository(Protocol):
    dataset_version: str
    def all(self) -> list[Story]: ...
    def get(self, story_id: str) -> Story | None: ...

class FixtureRepository:
    def __init__(self):
        data = json.loads((ROOT / 'contracts/fixtures.json').read_text(encoding='utf-8'))
        self.dataset_version = data['dataset_version']
        self.stories = [Story.model_validate(s) for s in data['stories']]

    def all(self):
        return list(self.stories)

    def get(self, story_id):
        return next((s for s in self.stories if s.id == story_id), None)
