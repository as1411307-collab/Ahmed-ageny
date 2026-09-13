from __future__ import annotations

import unittest

from run_state import RunStage, RunState


class RunStateTests(unittest.TestCase):
    def test_happy_path_is_deterministic(self) -> None:
        state = RunState()
        for stage in (
            RunStage.CONTEXT_LOADED,
            RunStage.MODEL_RUNNING,
            RunStage.RESPONSE_READY,
            RunStage.RESPONSE_PERSISTED,
            RunStage.COMPLETED,
        ):
            self.assertEqual(state.transition(stage), stage)
        self.assertEqual(state.stage, RunStage.COMPLETED)

    def test_failed_run_cannot_continue(self) -> None:
        state = RunState()
        state.transition(RunStage.CONTEXT_LOADED)
        state.transition(RunStage.MODEL_RUNNING)
        state.transition(RunStage.FAILED)
        with self.assertRaises(ValueError):
            state.transition(RunStage.RESPONSE_READY)

    def test_skipping_a_stage_is_rejected(self) -> None:
        state = RunState()
        with self.assertRaises(ValueError):
            state.transition(RunStage.COMPLETED)


if __name__ == "__main__":
    unittest.main()