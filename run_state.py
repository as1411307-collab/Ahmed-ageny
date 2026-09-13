from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStage(StrEnum):
    CREATED = "created"
    CONTEXT_LOADED = "context_loaded"
    MODEL_RUNNING = "model_running"
    RESPONSE_READY = "response_ready"
    RESPONSE_PERSISTED = "response_persisted"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RunStage, frozenset[RunStage]] = {
    RunStage.CREATED: frozenset({RunStage.CONTEXT_LOADED, RunStage.FAILED}),
    RunStage.CONTEXT_LOADED: frozenset({RunStage.MODEL_RUNNING, RunStage.FAILED}),
    RunStage.MODEL_RUNNING: frozenset({RunStage.RESPONSE_READY, RunStage.FAILED}),
    RunStage.RESPONSE_READY: frozenset({RunStage.RESPONSE_PERSISTED, RunStage.FAILED}),
    RunStage.RESPONSE_PERSISTED: frozenset({RunStage.COMPLETED, RunStage.FAILED}),
    RunStage.COMPLETED: frozenset(),
    RunStage.FAILED: frozenset(),
}


@dataclass
class RunState:
    stage: RunStage = RunStage.CREATED

    def transition(self, next_stage: RunStage) -> RunStage:
        if next_stage not in _ALLOWED_TRANSITIONS[self.stage]:
            raise ValueError(
                f"invalid run transition: {self.stage.value} -> {next_stage.value}"
            )
        self.stage = next_stage
        return self.stage