import logging
from vidbot import perfis


def _escrever(tmp_path, corpo):
    p = tmp_path / "x.yaml"
    p.write_text(corpo, encoding="utf-8")
    return p


def test_carrega_campos_declarados(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, """
nome: cortes_br
canal_token: cortes_br.json
reenquadre: rosto
max_cortes: 8
"""))
    assert p.nome == "cortes_br" and p.reenquadre == "rosto" and p.max_cortes == 8


def test_aplica_padroes_quando_o_yaml_e_minimo(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\n"))
    assert p.reenquadre == "centro"
    assert p.privacidade == "unlisted"
    assert p.idiomas == ["pt", "en"]


def test_reenquadre_invalido_cai_para_centro(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nreenquadre: holograma\n"))
    assert p.reenquadre == "centro"


def test_privacidade_invalida_cai_para_unlisted(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nprivacidade: secreto\n"))
    assert p.privacidade == "unlisted"


def test_estilo_tem_cores_validas(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nestilo:\n  cor_destaque: amarelo\n"))
    assert p.estilo["cor_destaque"] == "#FFD400"


def test_carregar_lista_yaml_retorna_perfil_com_padroes(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "- item1\n- item2\n"))
    assert p.nome != ""
    assert p.privacidade == "unlisted"


def test_carregar_string_yaml_retorna_perfil_com_padroes(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "hello world\n"))
    assert p.nome != ""
    assert p.reenquadre == "centro"


def test_carregar_numero_yaml_retorna_perfil_com_padroes(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "42\n"))
    assert p.nome != ""
    assert p.max_cortes == 12


def test_carregar_todos_alerta_sobre_nomes_duplicados(tmp_path, caplog):
    p1 = tmp_path / "a.yaml"
    p1.write_text("nome: duplicado\n", encoding="utf-8")
    p2 = tmp_path / "b.yaml"
    p2.write_text("nome: duplicado\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="vidbot.perfis"):
        resultado = perfis.carregar_todos(tmp_path)
    assert "duplicado" in resultado
    assert len(caplog.records) > 0
    assert "Perfil duplicado" in caplog.text


def test_auto_publicar_e_desligado_por_padrao(tmp_path):
    arq = tmp_path / "p.yaml"
    arq.write_text("nome: p\n", encoding="utf-8")
    assert perfis.carregar(arq).auto_publicar is False


def test_auto_publicar_liga_pelo_yaml(tmp_path):
    arq = tmp_path / "p.yaml"
    arq.write_text("nome: p\nauto_publicar: true\n", encoding="utf-8")
    assert perfis.carregar(arq).auto_publicar is True


def test_criterios_do_canal_sao_lidos(tmp_path):
    arq = tmp_path / "p.yaml"
    arq.write_text("nome: p\ncriterios: so momentos engracados\n", encoding="utf-8")
    assert perfis.carregar(arq).criterios == "so momentos engracados"
