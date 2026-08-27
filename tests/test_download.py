from pathlib import Path

import pytest

from vidbot import download as d


def test_metadados_nao_baixa_midia():
    assert d.opcoes_metadados()["skip_download"] is True


def test_secao_pede_apenas_o_intervalo():
    op = d.opcoes_secao(100.0, 160.0, Path("/tmp/x.mp4"))
    assert op["download_ranges"] is not None
    assert op["force_keyframes_at_cuts"] is True


def test_formato_prefere_h264_ate_1080p():
    assert "avc1" in d.opcoes_secao(0, 10, Path("/tmp/x.mp4"))["format"]
    assert "1080" in d.opcoes_secao(0, 10, Path("/tmp/x.mp4"))["format"]


def test_metadados_normaliza_o_dicionario_do_ytdlp():
    class FalsoYdl:
        def extract_info(self, url, download=False):
            return {"id": "A", "title": "Ep", "channel": "@x", "duration": 6000,
                    "chapters": [{"title": "c1", "start_time": 0}],
                    "subtitles": {}, "automatic_captions": {"pt": []}}

    m = d.metadados("https://youtu.be/A", ydl=FalsoYdl())
    assert m["video_id"] == "A" and m["duracao_s"] == 6000
    assert m["capitulos"][0]["title"] == "c1"


def test_metadados_tolera_campos_ausentes():
    class Magro:
        def extract_info(self, url, download=False):
            return {"id": "A"}

    m = d.metadados("https://youtu.be/A", ydl=Magro())
    assert m["titulo"] == "" and m["duracao_s"] == 0 and m["capitulos"] == []


def test_retenta_erro_transitorio_e_sucede():
    chamadas = []

    def instavel():
        chamadas.append(1)
        if len(chamadas) < 3:
            raise RuntimeError("connection reset")
        return "ok"

    assert d.com_retentativa(instavel, espera=lambda _s: None) == "ok"
    assert len(chamadas) == 3


def test_nao_retenta_video_privado():
    def privado():
        raise RuntimeError("Video is private")

    with pytest.raises(RuntimeError):
        d.com_retentativa(privado, tentativas=3, espera=lambda _s: None)


def test_secao_fixa_o_container_no_mp4():
    """Sem isto o merge do yt-dlp pode gravar .mkv e o caminho devolvido
    apontaria para um arquivo que nao existe."""
    assert d.opcoes_secao(0, 10, Path("/tmp/x.mp4"))["merge_output_format"] == "mp4"


class _YdlFalso:
    """Escreve onde mandarem, imitando o yt-dlp de verdade."""

    def __init__(self, escreve_em=None):
        self.escreve_em = escreve_em

    def download(self, urls):
        if self.escreve_em is not None:
            Path(self.escreve_em).write_bytes(b"video")


def test_baixar_secao_devolve_o_arquivo_que_saiu(tmp_path):
    destino = tmp_path / "c.mp4"
    saida = d.baixar_secao("u", 0, 10, destino, ydl=_YdlFalso(destino))
    assert saida == destino and saida.is_file()


def test_baixar_secao_acha_o_arquivo_remuxado_para_outra_extensao(tmp_path):
    """yt-dlp avisa 'merged into mkv' e grava com outro sufixo."""
    destino = tmp_path / "c.mp4"
    real = tmp_path / "c.mkv"
    saida = d.baixar_secao("u", 0, 10, destino, ydl=_YdlFalso(real))
    assert saida == real and saida.is_file()


def test_baixar_secao_falha_alto_quando_nada_foi_escrito(tmp_path):
    """Devolver um caminho fantasma so adiaria o erro para o ffmpeg."""
    with pytest.raises(d.DownloadVazio):
        d.baixar_secao("u", 0, 10, tmp_path / "c.mp4", ydl=_YdlFalso(None))
