from vidbot import estados as e


def test_job_novo_pode_ir_para_legenda_obtida():
    assert e.pode(e.TRANSICOES_JOB, e.NOVO, e.LEGENDA_OBTIDA)


def test_job_novo_pode_encerrar_sem_legenda():
    assert e.pode(e.TRANSICOES_JOB, e.NOVO, e.SEM_LEGENDA)


def test_job_nao_pula_direto_para_renderizado():
    assert not e.pode(e.TRANSICOES_JOB, e.NOVO, e.RENDERIZADO)


def test_estado_final_nao_transiciona():
    assert not e.pode(e.TRANSICOES_JOB, e.CONCLUIDO, e.SEGMENTADO)


def test_refazer_corte_devolve_o_job_para_segmentado():
    assert e.pode(e.TRANSICOES_JOB, e.RENDERIZADO, e.SEGMENTADO)


def test_corte_aprovado_publica():
    assert e.pode(e.TRANSICOES_CORTE, e.APROVADO, e.PUBLICADO)


def test_corte_com_erro_de_upload_retenta():
    assert e.pode(e.TRANSICOES_CORTE, e.ERRO_UPLOAD, e.APROVADO)


def test_corte_nao_publica_sem_passar_por_aprovado():
    assert not e.pode(e.TRANSICOES_CORTE, e.AGUARDANDO_APROVACAO, e.PUBLICADO)


def test_corte_recem_criado_pode_falhar_no_render():
    assert e.pode(e.TRANSICOES_CORTE, e.AGUARDANDO_APROVACAO, e.ERRO_RENDER)
