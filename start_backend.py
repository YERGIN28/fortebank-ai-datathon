"""Local single-process entry point. Configuration comes from .env."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="ForteBank backend, one analysis worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mode", choices=("fake", "real"), help="Override ANALYSIS_MODE from .env")
    args = parser.parse_args()
    if args.mode:
        os.environ["ANALYSIS_MODE"] = args.mode
    import uvicorn
    uvicorn.run("backend.main:app", host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
