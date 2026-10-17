"""Create full mock result fixtures for backend discussion, without loading Qwen."""
import argparse
from pathlib import Path
import json
import tempfile

from . import InferenceConfig, InferenceEngine
from .synthetic import create_video


class MockModel:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.calls = 0

    def load(self):
        pass

    def reset_metrics(self):
        pass

    def metrics(self):
        return {}

    def observe(self, frames, deadline):
        self.calls += 1
        if self.calls == 2:
            if self.scenario == 'partial':
                return [{'start_frame': 999}]
            if self.scenario == 'timeout':
                raise TimeoutError('Synthetic timeout')
        return [{'start_frame': 0, 'end_frame': 1,
                 'description': 'SYNTHETIC MOCK: cash remains on a desk after an attendant steps away.',
                 'type': 'cash_left_unattended', 'confidence': None, 'actors': ['cashier']}]


def create_results() -> dict:
    """Decode generated shapes, inject mock events; not detection evidence."""
    results = {}
    with tempfile.TemporaryDirectory(prefix='forte-contract-') as directory:
        path = Path(directory) / 'generated.mov'
        create_video(path, duration_seconds=16)
        config = InferenceConfig(model_path=Path('unused-mock'), refine=False)
        for status in ('complete', 'partial', 'timeout'):
            engine = InferenceEngine(config, model=MockModel(status))
            engine.load()
            result = engine.analyze_video(path)
            result.warnings.append('SYNTHETIC MOCK: events injected; no Qwen inference; not real data')
            if result.status != status:
                raise RuntimeError('Fixture status mismatch')
            results[status] = result.to_dict()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for status, payload in create_results().items():
        (args.output_dir / f'result_{status}.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Created three explicitly synthetic mock result fixtures')


if __name__ == '__main__':
    main()
