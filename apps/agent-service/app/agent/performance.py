"""Vendor-neutral digital-human micro-expression planning."""

from __future__ import annotations

from .models import ExpressionName, FillerPhase, PerformanceCue


class PerformancePlanner:
    """Map conversation phases to semantic cues understood by SDK adapters."""

    def for_listening(self) -> PerformanceCue:
        return PerformanceCue(
            expression=ExpressionName.LISTENING,
            intensity=0.32,
            durationMs=0,
            gaze="user",
            gesture="attentive",
            interruptible=True,
        )

    def for_phase(self, phase: FillerPhase) -> PerformanceCue:
        if phase == FillerPhase.THINKING:
            return PerformanceCue(
                expression=ExpressionName.THINKING,
                intensity=0.38,
                durationMs=900,
                gaze="away",
                gesture="small_nod",
                interruptible=True,
            )
        if phase == FillerPhase.ACKNOWLEDGE:
            return PerformanceCue(
                expression=ExpressionName.ACKNOWLEDGING,
                intensity=0.55,
                durationMs=500,
                gaze="user",
                gesture="acknowledge",
                interruptible=True,
            )
        if phase == FillerPhase.SPEAKING:
            return PerformanceCue(
                expression=ExpressionName.SPEAKING,
                intensity=0.48,
                durationMs=700,
                gaze="camera",
                lipSync=True,
                interruptible=True,
            )
        if phase == FillerPhase.INTERRUPTED:
            return PerformanceCue(
                expression=ExpressionName.INTERRUPTED,
                intensity=0.42,
                durationMs=450,
                gaze="user",
                gesture="pause",
                interruptible=True,
            )
        if phase == FillerPhase.COMPLETE:
            return PerformanceCue(
                expression=ExpressionName.RELIEVED,
                intensity=0.28,
                durationMs=500,
                gaze="camera",
                gesture="small_nod",
                interruptible=True,
            )
        return PerformanceCue(
            expression=ExpressionName.NEUTRAL,
            intensity=0.2,
            durationMs=400,
            gaze="camera",
            interruptible=True,
        )
