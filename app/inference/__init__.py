"""Local inference; no model loading or video access on import."""
from .pipeline import InferenceEngine, analyze_video
from .schemas import INFERENCE_VERSION, InferenceConfig, InferenceResult, Observation

__all__ = ['InferenceConfig', 'InferenceResult', 'Observation',
           'InferenceEngine', 'analyze_video', 'INFERENCE_VERSION']
