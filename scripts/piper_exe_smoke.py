from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 1:
        raise RuntimeError("Usage: piper_exe_smoke.py <EnglishSpellReader.exe>")

    exe_path = Path(args[0])
    if not exe_path.exists():
        raise RuntimeError(f"Executable was not found: {exe_path}")

    with tempfile.TemporaryDirectory(prefix="EnglishSpellReaderExeSmoke-") as temp_dir:
        temp_root = Path(temp_dir)
        output_path = temp_root / "piper-smoke.wav"
        job_path = temp_root / "piper-render-job.json"
        job_path.write_text(
            json.dumps(
                {
                    "output_path": str(output_path),
                    "source_text": "hello",
                    "rate": 200,
                    "volume": 1.0,
                    "english_voice_id": None,
                    "chinese_voice_id": None,
                    "units": [
                        {
                            "index": 0,
                            "source_text": "hello",
                            "span": {"start": 0, "end": 5},
                            "action": "read_word",
                            "voice_role": "english",
                            "speak_text": "hello",
                            "pause_ms": 0,
                            "audio_path": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(exe_path), "--piper-render", str(job_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"Packaged Piper smoke test failed with exit code {result.returncode}. {detail}"
            )

        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("Packaged Piper smoke test did not produce a WAV file.")

        with wave.open(str(output_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()

        if frames <= 0:
            raise RuntimeError("Packaged Piper smoke test produced an empty WAV.")

        print("Packaged Piper smoke test passed.")
        print(
            "WAV: channels={0} width={1} rate={2} frames={3}".format(
                channels,
                sample_width,
                frame_rate,
                frames,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
