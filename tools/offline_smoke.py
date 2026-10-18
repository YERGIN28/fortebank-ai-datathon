"""Fresh local model load and generated-video inference with socket calls denied.

Run only after stopping the GPU service. This is a process-level network guard,
not an operating-system firewall test. No real video path is accepted.
"""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.service_manager import initialize, health, PRIVATE


def main():
    if health() is not None:
        raise SystemExit('Stop the GPU service before this fresh-model smoke check.')
    values = initialize()
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(1)
        raise OSError('Network disabled for offline smoke check')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    from app.inference import InferenceConfig, InferenceEngine, INFERENCE_VERSION
    from app.inference.synthetic import create_video
    started = time.perf_counter()
    engine = InferenceEngine(InferenceConfig(
        model_path=Path(values['MODEL_PATH']),
        quantization=values.get('MODEL_QUANTIZATION','none'),
        max_frame_side=640, time_budget_seconds=120,
    ))
    engine.load()
    with tempfile.TemporaryDirectory(prefix='forte-offline-generated-') as directory:
        video=Path(directory)/'generated.mov'
        create_video(video)
        result=engine.analyze_video(video)
    report={
        'version':INFERENCE_VERSION,
        'model_name':Path(values['MODEL_PATH']).name,
        'quantization':values.get('MODEL_QUANTIZATION','none'),
        'input':'generated_shapes_only',
        'network_guard':'Python socket connection and DNS functions denied',
        'network_attempts':len(attempts),
        'status':result.status, 'observation_count':len(result.observations),
        'cold_start_and_analysis_sec':round(time.perf_counter()-started,3),
        'peak_allocated_mib':result.gpu_peak_allocated_mib,
    }
    report['passed']=result.status=='complete' and not result.observations and not attempts
    (PRIVATE/'results'/'offline_smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
