"""Painel de progresso do Telegram: uma mensagem, editada ate o fim.

O feedback e acessorio: nada aqui pode derrubar o processamento. Por isso a
formatacao e pura e o represamento vive junto dela, longe da rede.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

INTERVALO_MINIMO = 5.0


def agora() -> float:
    return time.monotonic()


@dataclass
class Painel:
    job_id: int
    canal: str
    inicio: float
    feitas: list[tuple[str, str]] = field(default_factory=list)
    atual: tuple[str, int, int] | None = None
    erro: tuple[str, str] | None = None
    _ultimo_envio: float = 0.0
    _ultimo_texto: str = ""

    def marcar(self, etapa: str, detalhe: str = "") -> None:
        self.feitas.append((etapa, detalhe))
        self.atual = None

    def andamento(self, etapa: str, feitos: int, total: int) -> None:
        self.atual = (etapa, feitos, total)

    def falhar(self, etapa: str, mensagem: str) -> None:
        self.erro = (etapa, mensagem)
        self.atual = None

    def _restante(self, feitos: int, total: int) -> str:
        if feitos <= 0:
            return ""
        decorrido = max(0.0, agora() - self.inicio)
        falta = decorrido / feitos * (total - feitos)
        return f" · ~{int(falta // 60)}min restante" if falta >= 60 else " · quase la"

    def texto(self) -> str:
        decorrido = int(max(0.0, agora() - self.inicio) // 60)
        linhas = [f"job #{self.job_id} · {self.canal} · decorrido {decorrido}min", ""]
        linhas += [f"[ok] {etapa}{f'   {det}' if det else ''}" for etapa, det in self.feitas]
        if self.atual:
            etapa, feitos, total = self.atual
            linhas.append(f"[..] {etapa}   {feitos}/{total}{self._restante(feitos, total)}")
        if self.erro:
            etapa, mensagem = self.erro
            linhas += [f"[!!] {etapa}", "", mensagem]
        return "\n".join(linhas)

    def deve_enviar(self, momento: float) -> bool:
        """True so quando o texto mudou E o intervalo minimo passou."""
        texto = self.texto()
        if texto == self._ultimo_texto:
            return False
        if self._ultimo_envio and momento - self._ultimo_envio < INTERVALO_MINIMO:
            return False
        self._ultimo_envio, self._ultimo_texto = momento, texto
        return True
