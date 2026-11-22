from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Palavra:
    inicio: float
    fim: float
    texto: str


@dataclass
class Segmento:
    inicio: float
    fim: float
    texto: str
    palavras: list[Palavra] = field(default_factory=list)


@dataclass
class Corte:
    inicio: float
    fim: float
    titulo: str
    nota: int = 0
    justificativa: str = ""
    descricao: str = ""
    hashtags: list[str] = field(default_factory=list)
    arquivo: str = ""

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


# Perfis de corte: duração mínima/máxima (segundos) e orientação para o LLM
PERFIS = {
    "curto": {
        "min": 20,
        "max": 60,
        "descricao": (
            "Cortes CURTOS para Shorts/Reels/TikTok. Cada corte deve abrir com um gancho "
            "forte nos primeiros 3 segundos, ter uma ideia completa e terminar de forma "
            "satisfatória (conclusão, punchline ou frase de impacto)."
        ),
    },
    "longo": {
        "min": 180,
        "max": 600,
        "descricao": (
            "Cortes LONGOS (capítulos / melhores momentos). Cada corte deve cobrir um "
            "assunto inteiro, com começo, meio e fim claros, entendível sem o resto do vídeo."
        ),
    },
}
