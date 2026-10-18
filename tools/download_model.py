"""One-time official weight download. Runtime inference never calls this module."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=('2B','4B'), default='4B')
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from huggingface_hub import HfApi, snapshot_download
    name = f'Qwen/Qwen3-VL-{args.size}-Instruct'
    revision = HfApi().model_info(name).sha
    snapshot_download(name, revision=revision, local_dir=args.destination,
                      allow_patterns=['*.json','*.safetensors','*.txt','*.jinja','README.md','LICENSE'])
    (args.destination/'download_revision.txt').write_text(revision, encoding='utf-8')
    print(f'Local weights ready: {name}, revision {revision}')


if __name__ == '__main__':
    main()
