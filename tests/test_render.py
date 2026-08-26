import shutil
from pathlib import Path

import pytest

from vidbot import render

sem_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg ausente")


def test_comando_queima_a_legenda_e_usa_h264():
    cmd = render.montar_comando(Path("e.mp4"), Path("l.ass"), Path("s.mp4"), "crop=1:2:3:0")
    linha = " ".join(cmd)
    assert "ass=" in linha and "libx264" in linha and cmd[0] == "ffmpeg"


def test_comando_passa_o_filtro_recebido():
    cmd = render.montar_comando(Path("e.mp4"), Path("l.ass"), Path("s.mp4"), "crop=9:9:9:0")
    assert "crop=9:9:9:0" in " ".join(cmd)


def test_comando_sobrescreve_sem_perguntar():
    assert "-y" in render.montar_comando(Path("e"), Path("l"), Path("s"), "f")


@sem_ffmpeg
def test_fumaca_gera_um_mp4_de_verdade(tmp_path):
    """Vídeo sintético de 2s criado pelo próprio ffmpeg — sem rede, sem fixture pesada."""
    entrada = render.gerar_video_de_teste(tmp_path / "e.mp4", segundos=2)
    ass = tmp_path / "l.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: P,DejaVu Sans,72\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:02.00,P,,0,0,0,,OI\n", encoding="utf-8")
    saida = render.renderizar(entrada, ass, tmp_path / "s.mp4", "scale=1080:1920")
    assert saida.exists() and saida.stat().st_size > 1000


@sem_ffmpeg
def test_entrada_invalida_levanta_falha_com_a_saida_do_ffmpeg(tmp_path):
    ruim = tmp_path / "nao_e_video.mp4"
    ruim.write_bytes(b"nada")
    with pytest.raises(render.FalhaFFmpeg):
        render.renderizar(ruim, tmp_path / "x.ass", tmp_path / "s.mp4", "scale=1080:1920")
