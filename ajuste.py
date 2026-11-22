from __future__ import annotations

from .modelos import PERFIS, Corte, Segmento

FIM_DE_FRASE = (".", "?", "!", "…")
PAUSA_ENTRE_FRASES = 0.7  # segundos de pausa que também contam como fim de frase


def fronteiras_de_frase(segmentos: list[Segmento]) -> tuple[list[float], list[float]]:
    """Devolve (inícios_de_frase, fins_de_frase) a partir dos timestamps por palavra."""
    palavras = [p for s in segmentos for p in s.palavras]
    if not palavras:  # sem timestamps por palavra: usa os segmentos
        return [s.inicio for s in segmentos], [s.fim for s in segmentos]

    inicios, fins = [palavras[0].inicio], []
    for i, p in enumerate(palavras):
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        terminou = (
            prox is None
            or p.texto.endswith(FIM_DE_FRASE)
            or (prox.inicio - p.fim) > PAUSA_ENTRE_FRASES
        )
        if terminou:
            fins.append(p.fim)
            if prox:
                inicios.append(prox.inicio)
    return inicios, fins


def _mais_proximo(valor: float, candidatos: list[float], tolerancia: float) -> float:
    if not candidatos:
        return valor
    melhor = min(candidatos, key=lambda c: abs(c - valor))
    return melhor if abs(melhor - valor) <= tolerancia else valor


def ajustar_corte(
    corte: Corte,
    inicios: list[float],
    fins: list[float],
    silencios: list[tuple[float, float]],
    duracao_total: float,
    tolerancia: float = 4.0,
) -> Corte:
    """Encaixa início/fim nas fronteiras de frase e dá um 'respiro' só dentro de silêncios."""
    ini = _mais_proximo(corte.inicio, inicios, tolerancia)
    fim = _mais_proximo(corte.fim, fins, tolerancia)

    # respiro no começo: recua até 0,25s se estiver colado num silêncio
    for s_ini, s_fim in silencios:
        if s_ini < ini <= s_fim + 0.05:
            ini = max(ini - 0.25, s_ini)
            break
    # respiro no final: avança até 0,35s sem invadir a próxima fala
    for s_ini, s_fim in silencios:
        if s_ini <= fim + 0.05 < s_fim:
            fim = min(fim + 0.35, s_fim)
            break

    ini = max(0.0, ini)
    fim = min(duracao_total, fim)
    if fim <= ini:  # ajuste deu errado: mantém o original
        ini, fim = corte.inicio, corte.fim
    corte.inicio, corte.fim = round(ini, 2), round(fim, 2)
    return corte


def ajustar_todos(
    cortes: list[Corte],
    segmentos: list[Segmento],
    silencios: list[tuple[float, float]],
    duracao_total: float,
    modo: str,
) -> list[Corte]:
    inicios, fins = fronteiras_de_frase(segmentos)
    perfil = PERFIS[modo]
    resultado = []
    for c in cortes:
        c = ajustar_corte(c, inicios, fins, silencios, duracao_total)
        # descarta o que ficou fora de uma faixa razoável após o ajuste
        if perfil["min"] * 0.7 <= c.duracao <= perfil["max"] * 1.3:
            resultado.append(c)
        else:
            print(f"  descartado (duração {c.duracao:.0f}s fora do esperado): {c.titulo}")
    return sorted(resultado, key=lambda c: c.inicio)
