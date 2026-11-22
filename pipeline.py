from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .ajuste import ajustar_todos
from .analise import detectar_silencios, duracao_video
from .corte import cortar_video
from .energia import selecionar_por_energia
from .ingestao import obter_video
from .modelos import Corte
from .selecao import escolher_motor, remover_sobrepostos, selecionar_cortes
from .transcricao import transcrever


def tem_fala(segmentos, duracao: float) -> bool:
    """True se a transcrição tem fala suficiente para escolher cortes pelo texto."""
    palavras = sum(len(s.palavras) or len(s.texto.split()) for s in segmentos)
    return palavras >= max(30, duracao / 60 * 8)


def planejar(video: Path, duracao: float, modo: str, qtd: int, trabalho: Path,
             whisper: str = "small", idioma: str | None = None, dispositivo: str = "auto",
             fala: str = "auto", etapa: Callable[[int, str], None] = lambda n, m: None
             ) -> tuple[list[Corte], list[str]]:
    """Decide ONDE cortar. fala = auto | sim | nao.
    Com fala, escolhe pelo texto; sem fala (ou se a fala não rendeu cortes suficientes),
    usa a energia do áudio e o movimento da imagem. Devolve (cortes, avisos)."""
    avisos: list[str] = []
    segmentos = []
    if fala == "nao":
        etapa(2, "Pulando a transcrição (modo sem fala)...")
    else:
        etapa(2, "Transcrevendo com Whisper (pode demorar em vídeos longos)...")
        segmentos = transcrever(video, trabalho, whisper, idioma, dispositivo)
    com_fala = tem_fala(segmentos, duracao)
    if fala != "nao" and not com_fala:
        avisos.append("Quase não há fala neste vídeo, então escolhi os momentos pela energia do áudio "
                      "e pelo movimento da imagem.")

    etapa(3, "Detectando silêncios...")
    silencios = detectar_silencios(video)

    cortes: list[Corte] = []
    if com_fala:
        nome = {"claude": "o Claude", "compativel": "a IA configurada",
                "local": "o modo gratuito (sem IA)"}[escolher_motor()]
        etapa(4, f"Escolhendo os melhores momentos com {nome}...")
        cortes = selecionar_cortes(segmentos, modo, qtd, duracao)
        etapa(5, "Ajustando os pontos de corte às frases...")
        cortes = ajustar_todos(cortes, segmentos, silencios, duracao, modo)
    else:
        etapa(4, "Analisando o áudio e o movimento do vídeo (pode demorar)...")

    if len(cortes) < qtd:  # sem fala, ou a fala rendeu menos do que o pedido: completa por energia
        if com_fala:
            etapa(5, "Completando com os momentos de maior energia...")
        extra = selecionar_por_energia(video, modo, qtd - len(cortes), duracao, trabalho,
                                       [(c.inicio, c.fim) for c in cortes])
        extra = ajustar_todos(extra, segmentos, silencios, duracao, modo)
        if cortes and extra:
            avisos.append(f"A fala rendeu só {len(cortes)} corte(s); completei com os momentos "
                          "de maior energia do áudio e da imagem.")
        cortes = remover_sobrepostos(cortes + extra)

    cortes = sorted(cortes, key=lambda c: c.inicio)[:qtd]
    if not cortes:
        raise RuntimeError("O vídeo é curto demais para gerar cortes neste modo. "
                           "Tente o modo Curtos ou um vídeo mais longo.")
    if len(cortes) < qtd:
        avisos.append(f"Só coube(ram) {len(cortes)} de {qtd} cortes neste vídeo ({duracao / 60:.1f} min). "
                      "Peça menos cortes ou use um vídeo mais longo.")
    return cortes, avisos


def processar(fonte: str, modo: str, qtd: int, pasta: Path, whisper: str = "small",
              idioma: str | None = None, etapa: Callable[[int, str], None] = lambda n, m: None,
              fala: str = "auto"):
    """Pipeline completo, com callback de progresso (usado pela interface web).
    Devolve (caminho_do_video, duracao, lista_de_cortes_como_dict, avisos)."""
    trabalho, saida = pasta / "_trabalho", pasta / "cortes"

    etapa(1, "Obtendo o vídeo...")
    video = obter_video(fonte, trabalho)
    duracao = duracao_video(video)

    cortes, avisos = planejar(video, duracao, modo, qtd, trabalho, whisper, idioma, "auto", fala, etapa)

    for i, c in enumerate(cortes, 1):
        etapa(6, f"Exportando o corte {i} de {len(cortes)}...")
        c.arquivo = cortar_video(video, c, saida, i).name
    return video, duracao, [asdict(c) for c in cortes], avisos
