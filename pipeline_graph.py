from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class PipelineStep(Generic[T]):
    name: str
    run: Callable[[T], T]
    when: Callable[[T], bool] = lambda _: True


class PipelineGraph(Generic[T]):
    """Small declarative, ordered graph. Steps describe flow; functions do work."""

    def __init__(self, steps: tuple[PipelineStep[T], ...]):
        names = [step.name for step in steps]
        if len(names) != len(set(names)):
            raise ValueError("pipeline step names must be unique")
        self.steps = steps

    def run(self, context: T) -> T:
        current = context
        for step in self.steps:
            if step.when(current):
                current = step.run(current)
        return current

    @property
    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps)
