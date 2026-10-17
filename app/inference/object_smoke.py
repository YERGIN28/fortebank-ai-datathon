"""Offline Qwen object check on invented cards/paper/shapes; no real input accepted."""
import argparse
import json
from pathlib import Path
import time

from . import InferenceConfig
from .model import QwenModel
from .video import SampledFrame


def artificial_image(kind):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (768, 432), '#c8b99b')
    draw = ImageDraw.Draw(image)
    if kind == 'id_document':
        draw.rounded_rectangle((170, 95, 600, 335), 18, fill='#d9eff7', outline='navy', width=4)
        draw.text((200, 115), 'SPECIMEN ID CARD - NOT VALID', fill='navy', font_size=19)
        draw.rectangle((195, 160, 290, 295), fill='#a3bdd1')
        draw.ellipse((220, 175, 265, 220), fill='#53697b')
        draw.rectangle((212, 225, 275, 280), fill='#53697b')
        for y in (165, 195, 225, 255, 285):
            draw.line((320, y, 560, y), fill='navy', width=3)
    elif kind == 'paper_document':
        draw.rectangle((250, 35, 530, 400), fill='white', outline='gray', width=3)
        draw.text((280, 60), 'DEMO RECEIPT', fill='black', font_size=20)
        for y in range(110, 355, 30):
            draw.line((280, y, 495, y), fill='#777777', width=2)
    else:
        draw.rectangle((160, 160, 260, 260), fill='red')
        draw.ellipse((450, 160, 550, 260), fill='blue')
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    model = QwenModel(InferenceConfig(args.model_path))
    model.load()
    model.reset_metrics()
    report = {'source': 'Invented PIL cards and shapes only; no personal data or real video', 'cases': []}
    for kind in ('id_document', 'paper_document', 'shapes'):
        image = artificial_image(kind)
        started = time.perf_counter()
        predicted = model.verify_object([SampledFrame(0, image), SampledFrame(1, image.copy())], started + 90)
        case = {'synthetic_kind': kind, 'predicted_kind': predicted,
                'elapsed_sec': time.perf_counter() - started, 'not_mislabeled_banknote': predicted != 'banknote'}
        report['cases'].append(case)
        print(json.dumps(case), flush=True)
    report.update(model.metrics())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not all(case['not_mislabeled_banknote'] for case in report['cases']):
        raise SystemExit('Synthetic negative object check failed; inspect report')


if __name__ == '__main__':
    main()
