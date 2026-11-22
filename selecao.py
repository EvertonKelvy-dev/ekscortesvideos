from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from types import SimpleNamespace

from .modelos import PERFIS, Corte, Segmento

MAX_CHARS_POR_BLOCO = 120_000  # ~30k tokens de transcrição por chamada

SYSTEM = """Você é o editor-chefe de um canal de vídeos, especialista em escolher os \
melhores momentos de vídeos longos. Você recebe a transcrição com marcação de tempo \
em segundos e devolve SOMENTE um JSON válido, sem texto antes ou depois, sem markdown."""


def escolher_motor() -> str:
    """claude (precisa de chave), compativel (qualquer IA estilo OpenAI, ex.: Ollama) ou local (grátis, sem IA)."""
    pedido = os.getenv("EKS_MOTOR", "auto").lower()
    if pedido in ("claude", "compativel", "local"):
        return pedido
    if os.getenv("ANTHROPIC_API_KEY", "") not in ("", "sua-chave-aqui"):
        return "claude"
    return "compativel" if os.getenv("EKS_LLM_URL") else "local"


class _Mensagens:
    def __init__(self, url: str, chave: str):
        self.url, self.chave = url.rstrip("/"), chave

    def create(self, model, max_tokens, system, messages):
        corpo = {"model": model, "max_tokens": max_tokens, "temperature": 0.3,
                 "messages": [{"role": "system", "content": system}, *messages]}
        cab = {"Content-Type": "application/json"}
        if self.chave:
            cab["Authorization"] = f"Bearer {self.chave}"
        req = urllib.request.Request(self.url + "/chat/completions", json.dumps(corpo).encode(), cab)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                dados = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"A IA configurada respondeu erro {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Não consegui falar com {self.url}: {e.reason}") from e
        texto = dados["choices"][0]["message"]["content"] or ""
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)])


class ClienteCompativel:
    """Cliente para qualquer API compatível com OpenAI (Ollama, Groq, OpenRouter, Gemini...)."""

    def __init__(self):
        self.messages = _Mensagens(os.environ["EKS_LLM_URL"], os.getenv("EKS_LLM_CHAVE", ""))


def formatar_transcricao(segmentos: list[Segmento]) -> str:
    return "\n".join(f"[{s.inicio:.1f}] {s.texto}" for s in segmentos if s.texto)


def dividir_em_blocos(segmentos: list[Segmento], max_chars: int = MAX_CHARS_POR_BLOCO):
    """Divide a transcrição em blocos para vídeos muito longos."""
    blocos, atual, tamanho = [], [], 0
    for s in segmentos:
        t = len(s.texto) + 12
        if atual and tamanho + t > max_chars:
            blocos.append(atual)
            atual, tamanho = [], 0
        atual.append(s)
        tamanho += t
    if atual:
        blocos.append(atual)
    return blocos


def _prompt(transcricao: str, modo: str, qtd: int) -> str:
    perfil = PERFIS[modo]
    return f"""{perfil['descricao']}

Escolha até {qtd} trechos. Regras:
- Duração de cada trecho: entre {perfil['min']} e {perfil['max']} segundos (fim - início).
- Use os tempos EXATOS da transcrição (em segundos). Comece no início de uma frase e \
termine no fim de uma frase; nunca corte no meio de uma ideia.
- Os trechos não podem se sobrepor.
- Priorize: gancho forte, emoção, humor, revelação, opinião polêmica, história completa, \
conclusão clara. Evite introduções, enrolação e trechos que dependem de contexto externo.
- "nota" é um inteiro de 0 a 100 com o potencial de engajamento.

Responda neste formato JSON exato:
{{"cortes": [{{"inicio": 0.0, "fim": 0.0, "titulo": "título chamativo", "nota": 85, \
"justificativa": "por que este trecho funciona", "descricao": "descrição para a postagem", \
"hashtags": ["#exemplo"]}}]}}

TRANSCRIÇÃO:
{transcricao}"""


def _extrair_json(texto: str) -> dict:
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini == -1 or fim == -1:
        raise ValueError("Resposta sem JSON")
    return json.loads(texto[ini : fim + 1])


def _perguntar(client, modelo: str, prompt: str) -> list[dict]:
    ultimo_erro = None
    for _ in range(2):  # uma nova tentativa se o JSON vier quebrado
        resp = client.messages.create(
            model=modelo,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _extrair_json(texto).get("cortes", [])
        except (ValueError, json.JSONDecodeError) as e:
            ultimo_erro = e
    raise RuntimeError(f"O modelo não devolveu um JSON válido: {ultimo_erro}")


def selecionar_cortes(
    segmentos: list[Segmento],
    modo: str,
    qtd: int,
    duracao_total: float,
    modelo: str | None = None,
    client=None,
) -> list[Corte]:
    """O 'cérebro' do agente: o Claude lê a transcrição e escolhe os melhores trechos."""
    motor = escolher_motor()
    if client is None and motor == "local":
        from .heuristica import selecionar_local

        print("  modo gratuito (sem IA): escolhendo pela pontuação do texto...")
        return selecionar_local(segmentos, modo, qtd, duracao_total)
    if client is None and motor == "compativel":
        if not (os.getenv("EKS_LLM_URL") and os.getenv("EKS_LLM_MODELO")):
            raise RuntimeError("Defina EKS_LLM_URL e EKS_LLM_MODELO no .env (veja o .env.example).")
        client, modelo = ClienteCompativel(), modelo or os.environ["EKS_LLM_MODELO"]
    elif client is None:
        import anthropic

        if os.getenv("ANTHROPIC_API_KEY", "") in ("", "sua-chave-aqui"):
            raise RuntimeError("Defina ANTHROPIC_API_KEY ou use o modo gratuito (EKS_MOTOR=local).")
        client = anthropic.Anthropic()
    modelo = modelo or os.getenv("EKS_MODELO_CLAUDE", "claude-sonnet-5-5")
    tam_bloco = int(os.getenv("EKS_BLOCO_CHARS", 20_000 if motor == "compativel" else MAX_CHARS_POR_BLOCO))

    brutos: list[dict] = []
    for i, bloco in enumerate(dividir_em_blocos(segmentos, tam_bloco), 1):
        print(f"  analisando bloco {i} com {modelo}...")
        brutos += _perguntar(client, modelo, _prompt(formatar_transcricao(bloco), modo, qtd))

    cortes: list[Corte] = []
    for c in brutos:
        try:
            ini, fim = float(c["inicio"]), float(c["fim"])
        except (KeyError, TypeError, ValueError):
            continue
        if fim <= ini or ini < 0 or ini >= duracao_total:
            continue
        cortes.append(
            Corte(
                inicio=ini,
                fim=min(fim, duracao_total),
                titulo=str(c.get("titulo", "Sem título")),
                nota=int(c.get("nota", 0) or 0),
                justificativa=str(c.get("justificativa", "")),
                descricao=str(c.get("descricao", "")),
                hashtags=[str(h) for h in c.get("hashtags", [])],
            )
        )
    return remover_sobrepostos(cortes)[:qtd]


def remover_sobrepostos(cortes: list[Corte]) -> list[Corte]:
    """Mantém os de maior nota e descarta os que se sobrepõem a eles."""
    mantidos: list[Corte] = []
    for c in sorted(cortes, key=lambda x: x.nota, reverse=True):
        if all(c.fim <= m.inicio or c.inicio >= m.fim for m in mantidos):
            mantidos.append(c)
    return mantidos
