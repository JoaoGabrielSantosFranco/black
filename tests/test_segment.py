from vidbot.captions import Palavra, Transcricao
from vidbot import segment as s


def _c(ini, fim, nota=50, titulo="t"):
    return s.Candidato(ini, fim, titulo, "gancho", nota)


def test_descarta_curto_demais():
    assert s.filtrar([_c(0, 5)]) == []


def test_descarta_longo_demais():
    assert s.filtrar([_c(0, 200)]) == []


def test_mantem_dentro_da_faixa():
    assert len(s.filtrar([_c(0, 40)])) == 1


def test_sobreposicao_grande_mantem_o_de_nota_maior():
    fraco, forte = _c(100, 160, nota=40, titulo="fraco"), _c(110, 170, nota=90, titulo="forte")
    assert [c.titulo for c in s.filtrar([fraco, forte])] == ["forte"]


def test_sobreposicao_pequena_mantem_os_dois():
    assert len(s.filtrar([_c(0, 60, nota=90), _c(55, 115, nota=80)])) == 2


def test_respeita_o_limite_de_cortes():
    muitos = [_c(i * 100, i * 100 + 40, nota=i) for i in range(20)]
    assert len(s.filtrar(muitos, max_cortes=5)) == 5


def test_ordena_por_nota_decrescente():
    r = s.filtrar([_c(0, 40, nota=10), _c(100, 140, nota=99)])
    assert [c.nota for c in r] == [99, 10]


def test_ajusta_a_borda_para_o_inicio_da_palavra_mais_proxima():
    palavras = [Palavra("a", 10.0, 10.5), Palavra("b", 10.5, 11.0), Palavra("c", 40.0, 40.4)]
    ajustado = s.ajustar_bordas(_c(10.3, 40.2), palavras)
    assert ajustado.inicio_s == 10.5
    assert ajustado.fim_s == 40.4


def test_ajuste_sem_palavras_nao_quebra():
    assert s.ajustar_bordas(_c(1.0, 2.0), []).inicio_s == 1.0


def test_coagir_grampeia_nota_e_ignora_item_sem_tempo():
    bruto = {"trechos": [
        {"inicio": 10, "fim": 50, "titulo": "ok", "gancho": "g", "nota": 999},
        {"titulo": "sem tempo"},
    ]}
    cands = s.coagir(bruto)
    assert len(cands) == 1 and cands[0].nota == 100


def test_coagir_descarta_intervalo_invertido():
    assert s.coagir({"trechos": [{"inicio": 90, "fim": 10, "nota": 50}]}) == []


def test_coagir_aceita_lista_na_raiz():
    assert len(s.coagir({"trechos": []})) == 0


def test_janelas_cobrem_todas_as_palavras():
    palavras = [Palavra("p" * 10, i, i + 1) for i in range(300)]
    js = s.janelas(palavras, max_chars=500, sobrep_chars=100)
    assert len(js) > 1
    assert js[0][0].texto == palavras[0].texto
    assert js[-1][-1].texto == palavras[-1].texto


def test_escolher_junta_as_janelas_e_filtra(monkeypatch):
    palavras = [Palavra("x", i, i + 1) for i in range(200)]
    t = Transcricao(palavras, "asr", "pt")

    def falso(prompt, sistema, cfg, **kw):
        return {"trechos": [{"inicio": 10, "fim": 50, "titulo": "a", "gancho": "g", "nota": 80}]}

    r = s.escolher(t, {"titulo": "Ep"}, cfg=None, perguntar=falso)
    assert len(r) == 1 and r[0].titulo == "a"
