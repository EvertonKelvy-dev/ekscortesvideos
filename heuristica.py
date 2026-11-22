"""Modo gratuito: escolhe os melhores trechos sem IA, só pontuando o texto da transcrição."""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass

from .ajuste import FIM_DE_FRASE, PAUSA_ENTRE_FRASES
from .modelos import PERFIS, Corte, Segmento

GANCHOS = set("""segredo segredos ninguém ninguem nunca jamais sempre erro erros dica dicas incrível incrivel
verdade mentira problema cuidado atenção atencao importante descobri surpreendente absurdo chocante melhor pior
grátis gratis dinheiro urgente perigo truque motivo razão lição aprendi revelação polêmico simples fácil facil
impossível impossivel secret never mistake truth best worst amazing free money tip secreto error verdad mejor peor""".split())
INTRO = set("""olá ola oi bem-vindos bem-vindo galera pessoal inscreva inscrevam canal like hello hi welcome hola
bienvenidos""".split())
ENCHIMENTO = set("tipo né ne então entao aí ai ah hm uh um éh eh hã".split())
PARADAS = set("""porque então quando porém assim fazer coisa coisas dessa nessa desse nesse muito ainda sobre também
tambem vocês voces vamos estou estava tinha aquilo agora depois antes mesmo seria pessoal gente about there their
which would could should where these those because""".split())


@dataclass
class Frase:
    inicio: float
    fim: float
    texto: str
    pontos: float = 0.0


def _palavras(texto: str) -> list[str]:
    return re.findall(r"[\wÀ-ÿ'-]+", texto.lower())


def montar_frases(segmentos: list[Segmento]) -> list[Frase]:
    palavras = [p for s in segmentos for p in s.palavras]
    if not palavras:
        return [Frase(s.inicio, s.fim, s.texto) for s in segmentos if s.texto]
    frases, buf = [], []
    for i, p in enumerate(palavras):
        buf.append(p)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        if prox is None or p.texto.endswith(FIM_DE_FRASE) or prox.inicio - p.fim > PAUSA_ENTRE_FRASES:
            frases.append(Frase(buf[0].inicio, buf[-1].fim, " ".join(w.texto for w in buf)))
            buf = []
    return frases


def pontuar(f: Frase) -> float:
    ws = _palavras(f.texto)
    n, dur = len(ws), max(f.fim - f.inicio, 0.1)
    p = 1.2 * min(f.texto.count("?"), 2) + 1.0 * min(f.texto.count("!"), 2)
    p += 0.8 * min(sum(w in GANCHOS for w in ws), 3)
    p += 0.5 * min(len(re.findall(r"\d+", f.texto)), 2)
    if 2.5 <= n / dur <= 4.5:  # fala fluida e animada
        p += 0.6
    if n < 4:
        p -= 1.0
    if n > 45:
        p -= 0.5
    p -= 3 * sum(w in ENCHIMENTO for w in ws) / max(n, 1)
    f.pontos = p
    return p


def _titulo(frases: list[Frase]) -> str:
    base = max(frases, key=lambda f: f.pontos).texto.strip().rstrip(".,;:")
    if len(base) > 70:
        base = base[:70].rsplit(" ", 1)[0] + "…"
    return base[:1].upper() + base[1:]


def _hashtags(frases: list[Frase], modo: str) -> list[str]:
    cont = Counter(w for f in frases for w in _palavras(f.texto)
                   if len(w) >= 5 and w not in PARADAS and not w.isdigit())
    tags = ["#" + w for w, _ in cont.most_common(3)]
    return tags + (["#shorts", "#cortes"] if modo == "curto" else ["#cortes"])


def selecionar_local(segmentos: list[Segmento], modo: str, qtd: int, duracao_total: float) -> list[Corte]:
    minimo, maximo = PERFIS[modo]["min"], PERFIS[modo]["max"]
    alvo = minimo + 0.45 * (maximo - minimo)
    frases = montar_frases(segmentos)
    for f in frases:
        pontuar(f)
    pref = [0.0]
    for f in frases:
        pref.append(pref[-1] + f.pontos)

    cands = []  # (nota_bruta, i, k): a melhor janela que começa em cada frase
    for i in range(len(frases)):
        melhor = None
        for k in range(i, len(frases)):
            dur = frases[k].fim - frases[i].inicio
            if dur > maximo:
                break
            if dur < minimo:
                continue
            media = (pref[k + 1] - pref[i]) / (k - i + 1)
            s = media - abs(dur - alvo) / alvo + 0.5 * max(frases[i].pontos, 0)
            if frases[k].texto.rstrip().endswith((".", "!", "?")):
                s += 0.3
            if any(w in INTRO for w in _palavras(frases[i].texto)):
                s -= 1.5
            buracos = sum(frases[j + 1].inicio - frases[j].fim > 2.5 for j in range(i, k))
            s -= 0.4 * min(buracos, 3)
            if melhor is None or s > melhor[0]:
                melhor = (s, i, k)
        if melhor:
            cands.append(melhor)

    todas = sorted(c[0] for c in cands)
    escolhidos: list[tuple] = []
    for s, i, k in sorted(cands, reverse=True):
        ini, fim = frases[i].inicio, frases[k].fim
        if all(fim <= frases[b].inicio or ini >= frases[e].fim for _, b, e in escolhidos):
            escolhidos.append((s, i, k))
        if len(escolhidos) == qtd:
            break

    cortes = []
    for s, i, k in escolhidos:
        jan = frases[i : k + 1]
        pct = bisect_left(todas, s) / max(len(todas) - 1, 1)
        perguntas = sum(f.texto.count("?") for f in jan)
        exclam = sum(f.texto.count("!") for f in jan)
        motivos = [f"trecho de {jan[-1].fim - jan[0].inicio:.0f}s começando e terminando em frases completas"]
        if perguntas or exclam:
            motivos.append(f"{perguntas} pergunta(s) e {exclam} exclamação(ões)")
        if jan[0].pontos > 1:
            motivos.append("abre com uma frase forte")
        cortes.append(Corte(
            inicio=jan[0].inicio, fim=min(jan[-1].fim, duracao_total),
            titulo=_titulo(jan), nota=round(50 + 45 * pct),
            justificativa="Modo gratuito (sem IA): " + "; ".join(motivos) + ".",
            descricao=" ".join(f.texto for f in jan[:2])[:180],
            hashtags=_hashtags(jan, modo),
        ))
    return cortes
