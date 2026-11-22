from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .modelos import Palavra, Segmento


def _salvar(segmentos: list[Segmento], caminho: Path) -> None:
    caminho.write_text(
        json.dumps([asdict(s) for s in segmentos], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _carregar(caminho: Path) -> list[Segmento]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return [
        Segmento(
            inicio=s["inicio"],
            fim=s["fim"],
            texto=s["texto"],
            palavras=[Palavra(**p) for p in s["palavras"]],
        )
        for s in dados
    ]


def transcrever(
    video: Path,
    pasta_trabalho: Path,
    modelo: str = "small",
    idioma: str | None = None,
    dispositivo: str = "auto",
) -> list[Segmento]:
    """Transcreve com faster-whisper (local), com timestamps por palavra.
    O resultado fica em cache, então rodar de novo no mesmo vídeo é instantâneo."""
    cache = pasta_trabalho / f"{video.stem}.transcricao.json"
    if cache.exists():
        print(f"  usando transcrição em cache: {cache.name}")
        return _carregar(cache)

    from faster_whisper import WhisperModel  # import tardio: é pesado

    def rodar(disp: str, tipo: str) -> list[Segmento]:
        print(f"  carregando modelo Whisper '{modelo}' ({disp})...")
        whisper = WhisperModel(modelo, device=disp, compute_type=tipo)
        iterador, info = whisper.transcribe(
            str(video), language=idioma, word_timestamps=True, vad_filter=True
        )
        print(f"  idioma: {info.language} | duração: {info.duration:.0f}s")
        saida: list[Segmento] = []
        for seg in iterador:
            saida.append(
                Segmento(
                    inicio=seg.start,
                    fim=seg.end,
                    texto=seg.text.strip(),
                    palavras=[
                        Palavra(inicio=w.start, fim=w.end, texto=w.word.strip())
                        for w in (seg.words or [])
                    ],
                )
            )
            if info.duration:
                print(f"\r  transcrevendo... {min(100, seg.end / info.duration * 100):5.1f}%", end="")
        print()
        return saida

    try:
        segmentos = rodar(dispositivo, "default")
    except Exception as e:  # ex.: GPU/CUDA mal configurada
        if "metadata_errors" in str(e):
            raise RuntimeError(
                "O pacote 'av' instalado é novo demais para o faster-whisper. Feche o programa e dê dois "
                "cliques em iniciar.bat (ou rode: .\\.venv\\Scripts\\python.exe -m pip install \"av<19\")."
            ) from e
        if dispositivo == "cpu":
            raise
        print(f"\n  falhou com '{dispositivo}' ({e}). Tentando na CPU...")
        segmentos = rodar("cpu", "int8")

    _salvar(segmentos, cache)
    return segmentos
