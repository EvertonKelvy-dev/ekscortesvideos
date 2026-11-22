from __future__ import annotations

import re
import subprocess
from pathlib import Path


def duracao_video(video: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(res.stdout.strip())


def detectar_silencios(
    video: Path, ruido_db: int = -35, duracao_min: float = 0.4
) -> list[tuple[float, float]]:
    """Lista de (início, fim) dos silêncios, via ffmpeg silencedetect."""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-vn", "-af", f"silencedetect=noise={ruido_db}dB:d={duracao_min}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", res.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", res.stderr)]
    silencios = []
    for i, ini in enumerate(inicios):
        fim = fins[i] if i < len(fins) else duracao_video(video)
        silencios.append((max(0.0, ini), fim))
    return silencios
