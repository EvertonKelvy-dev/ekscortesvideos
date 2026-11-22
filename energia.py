"""Escolha de cortes sem depender de fala: usa a energia do áudio (tiros, explosões, música,
gritos) e o movimento da imagem. Serve para gameplay, trailers, esporte, qualquer vídeo sem
comentário, e também completa os cortes quando a fala rende menos do que o pedido."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np

from .modelos import PERFIS, Corte

MARGEM = 2          # segundos livres entre um corte e outro
VERSAO_CACHE = 1


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _ajustar(x, n: int, pad: float) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.full(n - len(x), pad, dtype=np.float32)])


def _media_movel(x: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")


def _rank(x: np.ndarray) -> np.ndarray:
    ordem = np.argsort(np.argsort(x, kind="stable"), kind="stable")
    return (ordem / max(len(x) - 1, 1)).astype(np.float32)


def _perfil_audio(video: Path, n: int) -> np.ndarray | None:
    """Volume (dB) de cada segundo. None se o vídeo não tem áudio."""
    sr = 8000
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    bloco, resto, rms = sr * 2, b"", []
    while True:
        dados = p.stdout.read(bloco * 30)
        if not dados:
            break
        resto += dados
        k = len(resto) // bloco
        if k:
            a = np.frombuffer(resto[: k * bloco], dtype=np.int16).astype(np.float32).reshape(k, sr) / 32768.0
            rms.extend(np.sqrt((a * a).mean(axis=1)).tolist())
            resto = resto[k * bloco:]
    p.wait()
    if not rms:
        return None
    db = 20 * np.log10(np.maximum(np.array(rms, dtype=np.float32), 1e-5))
    return _ajustar(db, n, float(db.min()))


def _perfil_movimento(video: Path, n: int, fps: int = 2, w: int = 64, h: int = 36) -> np.ndarray | None:
    """Quanto a imagem muda a cada segundo (ação, cortes de cena). None se não houver vídeo."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-an",
           "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    fs, resto, prev, difs = w * h, b"", None, []
    while True:
        dados = p.stdout.read(fs * 240)
        if not dados:
            break
        resto += dados
        k = len(resto) // fs
        if not k:
            continue
        frames = np.frombuffer(resto[: k * fs], dtype=np.uint8).reshape(k, fs).astype(np.float32)
        resto = resto[k * fs:]
        if prev is not None:
            frames = np.vstack([prev[None, :], frames])
        if len(frames) > 1:
            difs.extend(np.abs(np.diff(frames, axis=0)).mean(axis=1).tolist())
        prev = frames[-1]
    p.wait()
    if not difs:
        return None
    d = np.array(difs, dtype=np.float32)
    seg = np.minimum(((np.arange(len(d)) + 1) / fps).astype(int), n - 1)
    soma = np.bincount(seg, weights=d, minlength=n)[:n]
    cont = np.bincount(seg, minlength=n)[:n]
    return soma / np.maximum(cont, 1)


def _score_audio(db: np.ndarray | None) -> np.ndarray | None:
    if db is None or float(np.ptp(db)) < 3:  # sem áudio, ou volume praticamente constante
        return None
    suave = _media_movel(db, 3)
    sobe = np.maximum(0, np.diff(db, prepend=db[0]))  # subida brusca = tiro, explosão, grito
    sobe = np.clip(sobe / (np.percentile(sobe, 95) + 1e-6), 0, 1)
    return 0.7 * _rank(suave) + 0.3 * sobe


def _score_movimento(mov: np.ndarray | None) -> np.ndarray | None:
    if mov is None or float(np.ptp(mov)) < 1e-3:
        return None
    return _rank(_media_movel(mov, 3))


def calcular_score(video: Path, duracao: float, trabalho: Path | None = None) -> np.ndarray:
    """Nota de 0 a 1 para cada segundo do vídeo (fica em cache na pasta de trabalho)."""
    n = max(1, int(math.ceil(duracao)))
    cache = None
    if trabalho is not None:
        cache = Path(trabalho) / f"{video.stem}.energia.json"
        if cache.exists():
            try:
                d = json.loads(cache.read_text(encoding="utf-8"))
                if d.get("v") == VERSAO_CACHE and len(d["score"]) == n:
                    print("  usando análise de energia em cache")
                    return np.array(d["score"], dtype=np.float32)
            except (ValueError, KeyError, OSError):
                pass
    print("  analisando o áudio...")
    sa = _score_audio(_perfil_audio(video, n))
    print("  analisando o movimento da imagem...")
    sm = _score_movimento(_perfil_movimento(video, n))
    partes = [(s, p) for s, p in ((sa, 0.55), (sm, 0.45)) if s is not None]
    if partes:
        score = np.average([s for s, _ in partes], axis=0, weights=[p for _, p in partes]).astype(np.float32)
    else:
        score = np.zeros(n, dtype=np.float32)
    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"v": VERSAO_CACHE, "score": [round(float(x), 4) for x in score]}),
                             encoding="utf-8")
        except OSError:
            pass
    return score


def _gulosa(cum: np.ndarray, n: int, L: int, qtd: int, livre0: np.ndarray) -> list[tuple[int, int, float]]:
    """Pega, uma a uma, as janelas de L segundos com a melhor nota que ainda cabem."""
    livre = livre0.copy()
    achadas: list[tuple[int, int, float]] = []
    while len(achadas) < qtd:
        fc = np.concatenate([[0], np.cumsum(livre)])
        ok = (fc[L:] - fc[:-L]) == L                 # janelas que começam em t = 0..n-L e estão livres
        if not ok.any():
            break
        media = (cum[L:] - cum[:-L]) / L
        H = min(3, L)
        gancho = (cum[H:H + len(media)] - cum[:len(media)]) / H   # força dos 3 primeiros segundos
        v = media + 0.3 * gancho
        v[~ok] = -np.inf
        t = int(np.argmax(v))
        achadas.append((t, t + L, float(media[t])))
        livre[max(0, t - MARGEM): t + L + MARGEM] = False
    return achadas


def melhores_janelas(score: np.ndarray, qtd: int, minimo: float, maximo: float,
                     ocupados=()) -> list[tuple[int, int, float]]:
    """Escolhe até `qtd` janelas (início, fim, nota) que não se sobrepõem. Usa a duração ideal
    e, se não couberem `qtd` cortes, vai encurtando (até o mínimo) para caber o máximo possível."""
    n = len(score)
    livre = np.ones(n, dtype=bool)
    for ini, fim in ocupados:
        livre[max(0, int(ini) - MARGEM): min(n, int(math.ceil(fim)) + MARGEM)] = False
    cum = np.concatenate([[0.0], np.cumsum(score, dtype=np.float64)])
    alvo, minimo = int(minimo + 0.45 * (maximo - minimo)), int(minimo)
    passo = max(1, (alvo - minimo) // 8)
    melhor: list[tuple[int, int, float]] = []
    for L in list(range(alvo, minimo - 1, -passo)) + [minimo]:
        L = int(min(L, n))
        if L < 5:
            continue
        achadas = _gulosa(cum, n, L, qtd, livre)
        if len(achadas) > len(melhor):
            melhor = achadas
        if len(melhor) >= qtd:
            break
    return sorted(melhor)


def selecionar_por_energia(video: Path, modo: str, qtd: int, duracao: float,
                           trabalho: Path | None = None, ocupados=()) -> list[Corte]:
    if qtd <= 0:
        return []
    perfil = PERFIS[modo]
    score = calcular_score(video, duracao, trabalho)
    cortes = []
    for ini, fim, media in melhores_janelas(score, qtd, perfil["min"], perfil["max"], ocupados):
        fim = min(float(fim), duracao)
        cortes.append(Corte(
            inicio=float(ini), fim=fim,
            titulo=f"Momento de destaque ({_mmss(ini)})",
            nota=int(round(40 + 55 * float(np.clip(media, 0, 1)))),
            justificativa="Escolhido pela energia do áudio e pelo movimento da imagem, sem depender de fala.",
            descricao=f"Trecho de {fim - ini:.0f}s com bastante ação, a partir de {_mmss(ini)}.",
            hashtags=["#shorts", "#cortes"] if modo == "curto" else ["#cortes"],
        ))
    return cortes
