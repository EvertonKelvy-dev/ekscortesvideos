from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from . import __version__
from .analise import duracao_video
from .corte import cortar_video
from .ingestao import obter_video
from .modelos import PERFIS
from .pipeline import planejar


def _tempo(s: float) -> str:
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ekscortesvideo",
        description="EKScortesvideo: agente de IA que corta vídeos longos em cortes curtos ou longos.",
    )
    p.add_argument("fonte", help="caminho do vídeo ou link (YouTube etc.)")
    p.add_argument("-m", "--modo", choices=PERFIS.keys(), default="curto",
                   help="curto (20-60s) ou longo (3-10min). Padrão: curto")
    p.add_argument("-n", "--qtd", type=int, default=5, help="quantidade de cortes (padrão: 5)")
    p.add_argument("-o", "--saida", default="saida", help="pasta de saída (padrão: ./saida)")
    p.add_argument("--fala", choices=["auto", "sim", "nao"], default="auto",
                   help="usar a fala do vídeo? auto (padrão), sim ou nao (só áudio e movimento, "
                        "para gameplay sem comentário; também pula o Whisper)")
    p.add_argument("--whisper", default="small",
                   help="modelo do Whisper: tiny, base, small, medium, large-v3 (padrão: small)")
    p.add_argument("--idioma", default=None, help="idioma do vídeo, ex.: pt (padrão: detectar)")
    p.add_argument("--dispositivo", default="auto", choices=["auto", "cpu", "cuda"])
    p.add_argument("--so-analisar", action="store_true",
                   help="só escolhe os trechos (gera cortes.json), sem exportar os vídeos")
    p.add_argument("--versao", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("Erro: ffmpeg não encontrado. Instale em https://ffmpeg.org/download.html")
        return 1

    saida = Path(args.saida)
    trabalho = saida / "_trabalho"

    print("[1/6] Obtendo vídeo...")
    video = obter_video(args.fonte, trabalho)
    duracao = duracao_video(video)
    print(f"  {video.name} ({duracao / 60:.1f} min)")

    try:
        cortes, avisos = planejar(video, duracao, args.modo, args.qtd, trabalho, args.whisper,
                                  args.idioma, args.dispositivo, args.fala,
                                  etapa=lambda n, m: print(f"[{n}/6] {m}"))
    except RuntimeError as e:
        print(f"Erro: {e}")
        return 2
    for a in avisos:
        print(f"  aviso: {a}")

    print(f"[6/6] {'Resumo' if args.so_analisar else 'Exportando'}...")
    for i, c in enumerate(cortes, 1):
        if not args.so_analisar:
            c.arquivo = cortar_video(video, c, saida, i).name
        print(f"  {i:02d}. [{_tempo(c.inicio)} → {_tempo(c.fim)}] "
              f"({c.duracao:.0f}s) nota {c.nota} | {c.titulo}")

    saida.mkdir(parents=True, exist_ok=True)
    meta = saida / "cortes.json"
    meta.write_text(json.dumps([asdict(c) for c in cortes], ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\nPronto! Metadados (título, descrição, hashtags) em: {meta}")
    return 0


def main_cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_cli()
