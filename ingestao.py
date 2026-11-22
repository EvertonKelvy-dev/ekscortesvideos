from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def eh_url(fonte: str) -> bool:
    return fonte.lower().startswith(("http://", "https://"))


def obter_video(fonte: str, pasta_trabalho: Path) -> Path:
    """Devolve o caminho local do vídeo. Se for link, baixa com yt-dlp."""
    pasta_trabalho.mkdir(parents=True, exist_ok=True)

    if not eh_url(fonte):
        caminho = Path(fonte).expanduser().resolve()
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
        return caminho

    modelo_saida = str(pasta_trabalho / "%(id)s.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", modelo_saida,
        "--print", "after_move:filepath",
        "--no-simulate",
        fonte,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Falha ao baixar o vídeo:\n{res.stderr[-600:]}")

    linhas = [l for l in res.stdout.splitlines() if l.strip()]
    if not linhas:
        raise RuntimeError("yt-dlp não informou o arquivo baixado.")
    return Path(linhas[-1])
