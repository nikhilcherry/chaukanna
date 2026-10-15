from abc import ABC, abstractmethod

from schemas import Verdict
from store import CallState


class Backend(ABC):
    name = "base"

    @abstractmethod
    async def classify(self, call_id: str, st: CallState) -> Verdict: ...
