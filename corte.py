from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path

from .modelos import Corte


def _slug(texto: str, limite: int = 50) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite] or "corte"


def cortar_video(video: Path, corte: Corte, pasta_saida: Path, indice: int) -> Path:
    """Exporta o trecho com ffmpeg. Reencoda (libx264/aac) para o corte ser exato no frame."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / f"{indice:02d}_{_slug(corte.titulo)}.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{corte.inicio:.3f}",
        "-i", str(video),
        "-t", f"{corte.duracao:.3f}",
        "-map", "0:v:0?", "-map", "0:a:0?",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(destino),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{res.stderr[-600:]}")
    return destino
