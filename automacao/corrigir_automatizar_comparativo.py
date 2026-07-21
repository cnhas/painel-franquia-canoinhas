"""
Script de correcao pontual (rodar 1x): estende automacao/scrape_dia_datamuch.py
pra coletar automaticamente o comparativo com o mesmo dia do mes anterior
(usando report/208 - Acompanhamento de Operacao), em vez de precisar fazer
isso manualmente clicando no navegador (que foi o que tive que fazer em
21/07/2026 pros dias 16-19/07, por causa de um problema real de automacao de
clique no calendario dessa pagina).

DESCOBERTA que destrava isso: o proprio scrape_dia_datamuch.py ja documentava
(no comentario de selecionar_dia_unico) que os campos de Data dos OUTROS 3
relatorios (Lojas/Cupons/Ofertas) sao inputs de verdade com aria-label "Data
de inicio"/"Data de termino", preenchiveis direto com .fill() - sem precisar
clicar em calendario nenhum. report/208 usa o MESMO tipo de campo, so que ja
visivel na tela (nao escondido atras de um icone de funil) - entao a mesma
tecnica .fill() funciona, so pulando abrir_painel_filtro().

Tambem ajusta main() pra ter um valor padrao pra DIAS_ALVO quando rodar via
agendamento (cron) sem input manual: usa "ontem" (fuso America/Sao_Paulo),
que e o ultimo dia normalmente ja fechado no Data Much.

NAO muda o workflow .github/workflows/atualizar-dias-datamuch.yml (isso o
bot nunca consegue commitar - precisa editar direto pela web, feito em
seguida, separadamente).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "automacao" / "scrape_dia_datamuch.py"


def aplicar(texto: str, antigo: str, novo: str, nome: str) -> str:
    if antigo not in texto:
        print(f"::warning::[{nome}] trecho antigo nao encontrado - talvez ja corrigido. Pulando.")
        return texto
    texto = texto.replace(antigo, novo, 1)
    print(f"Corrigido: {nome}")
    return texto


def main():
    if not SCRIPT_PATH.exists():
        print(f"::error::{SCRIPT_PATH} nao encontrado.")
        return
    texto = SCRIPT_PATH.read_text(encoding="utf-8")

    # 1) import de zoneinfo pro calculo de "ontem" com fuso correto
    texto = aplicar(
        texto,
        "from datetime import date, datetime, timedelta",
        "from datetime import date, datetime, timedelta\nfrom zoneinfo import ZoneInfo",
        "import zoneinfo",
    )

    # 2) URL do report/208
    texto = aplicar(
        texto,
        'URL_OFERTAS = "https://datamuch.deliverymuch.com.br/app/report/434"',
        'URL_OFERTAS = "https://datamuch.deliverymuch.com.br/app/report/434"\n'
        'URL_OPERACAO = "https://datamuch.deliverymuch.com.br/app/report/208"',
        "URL_OPERACAO",
    )

    # 3) novas funcoes de coleta do comparativo - inseridas logo apos o fim
    #    de selecionar_dia_unico() (antes de "def ler_cards_ofertas").
    ANCORA_ANTIGA = "def ler_cards_ofertas(frame) -> dict:"
    FUNCOES_NOVAS = '''def selecionar_dia_unico_sem_filtro(frame, dia: date):
    """Igual a selecionar_dia_unico(), mas pro report/208 (Acompanhamento de
    Operacao) - la os campos de Data ja ficam visiveis direto na tela, nao
    escondidos atras de um icone de funil, entao pula abrir_painel_filtro().
    Confirmado manualmente (sessao de 21/07/2026, via cliques no navegador)
    que preencher os dois campos com o MESMO dia isola o GMV/Meta de UM dia
    so nos cards do topo."""
    data_str = dia.strftime("%d/%m/%Y")
    campo_inicio = frame.get_by_label(re.compile("Data de in[íi]cio", re.I)).first
    campo_fim = frame.get_by_label(re.compile(r"Data de t[ée]rmino", re.I)).first
    campo_inicio.fill(data_str)
    campo_inicio.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 500)
    campo_fim.fill(data_str)
    campo_fim.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 2000)


def ler_gmv_meta_dia_unico(frame) -> tuple:
    """Le os cards GMV (Realizado) e Meta do report/208 ja filtrado pra um
    unico dia. Retorna (gmv, meta). Regex desenhada a partir de observacao
    visual real (screenshots), no mesmo espirito das outras ler_cards_*."""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_gmv = re.search(r"\\bGMV\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Realizado", texto)
        m_meta = re.search(r"\\bMeta\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Meta\\b", texto)
        if m_gmv and m_meta:
            return round(parse_valor_brl(m_gmv.group(1)), 2), round(parse_valor_brl(m_meta.group(1)), 2)
        if time.monotonic() >= limite:
            raise RuntimeError(f"Nao achei os cards GMV/Meta do report/208. Texto: {texto[:1500]!r}")
        _esperar(frame, 500)


def coletar_comparativo_mes_anterior(page, dia: date) -> dict:
    """Pra um dia X, coleta GMV/Meta do proprio dia X e do mesmo dia no mes
    anterior via report/208 (Acompanhamento de Operacao), e retorna o bloco
    comparativo_mes_anterior pronto pra gravar em dias[]."""
    primeiro_dia_mes_atual = dia.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    dia_no_mes_anterior = min(dia.day, ultimo_dia_mes_anterior.day)
    data_mes_anterior = ultimo_dia_mes_anterior.replace(day=dia_no_mes_anterior)

    frame_operacao = obter_frame(page, URL_OPERACAO)
    selecionar_dia_unico_sem_filtro(frame_operacao, data_mes_anterior)
    gmv_mes_anterior, meta_mes_anterior = ler_gmv_meta_dia_unico(frame_operacao)

    frame_operacao2 = obter_frame(page, URL_OPERACAO)
    selecionar_dia_unico_sem_filtro(frame_operacao2, dia)
    gmv_dia, _meta_dia = ler_gmv_meta_dia_unico(frame_operacao2)

    variacao_pct = round((gmv_dia / gmv_mes_anterior - 1) * 100, 2) if gmv_mes_anterior else None

    return {
        "dia_mes_anterior": data_mes_anterior.strftime("%Y-%m-%d"),
        "gmv_mes_anterior": gmv_mes_anterior,
        "meta_mes_anterior": meta_mes_anterior,
        "variacao_pct": variacao_pct,
    }


def ler_cards_ofertas(frame) -> dict:'''

    texto = aplicar(texto, ANCORA_ANTIGA, FUNCOES_NOVAS, "funcoes de comparativo_mes_anterior")

    # 4) wire dentro de coletar_dia(): coleta o comparativo tambem, sem
    #    derrubar o dia inteiro se falhar (so registra pendencia).
    TRECHO_COLETAR_DIA_ANTIGO = '''    frame_ofertas = obter_frame(page, URL_OFERTAS)
    selecionar_dia_unico(frame_ofertas, dia)
    dados_ofertas = ler_cards_ofertas(frame_ofertas)
    print(f"Ofertas De/Por: {dados_ofertas['itens_vendidos']} itens.")

    return {
        "data": dia.strftime("%Y-%m-%d"),
        **dados_cupons_para_dia(dados_cupons),
        "ofertas_de_por": dados_ofertas,
        "top_lojas_gmv": top_gmv,
        "top_lojas_pedidos": top_pedidos,
        "pendencias": [
            "Dados do Painel (pedidos totais/cancelados/entrega/retirada) ainda não incluídos "
            "nesta atualização automática — só os dados do Data Much.",
        ],
    }'''

    TRECHO_COLETAR_DIA_NOVO = '''    frame_ofertas = obter_frame(page, URL_OFERTAS)
    selecionar_dia_unico(frame_ofertas, dia)
    dados_ofertas = ler_cards_ofertas(frame_ofertas)
    print(f"Ofertas De/Por: {dados_ofertas['itens_vendidos']} itens.")

    pendencias = [
        "Dados do Painel (pedidos totais/cancelados/entrega/retirada) ainda não incluídos "
        "nesta atualização automática — só os dados do Data Much.",
    ]

    comparativo_mes_anterior = None
    try:
        comparativo_mes_anterior = coletar_comparativo_mes_anterior(page, dia)
        print(f"Comparativo mês anterior: {comparativo_mes_anterior}")
    except Exception as e:
        print(f"::warning::Não consegui coletar comparativo_mes_anterior para {dia}: {e}")
        pendencias.append(
            "Comparativo com o mesmo dia do mês anterior não pôde ser coletado automaticamente "
            "nesta rodada (ver log de warning) — fica pendente pra próxima."
        )

    resultado = {
        "data": dia.strftime("%Y-%m-%d"),
        **dados_cupons_para_dia(dados_cupons),
        "ofertas_de_por": dados_ofertas,
        "top_lojas_gmv": top_gmv,
        "top_lojas_pedidos": top_pedidos,
        "pendencias": pendencias,
    }
    if comparativo_mes_anterior is not None:
        resultado["comparativo_mes_anterior"] = comparativo_mes_anterior
    return resultado'''

    texto = aplicar(texto, TRECHO_COLETAR_DIA_ANTIGO, TRECHO_COLETAR_DIA_NOVO, "wire comparativo em coletar_dia()")

    # 5) default de DIAS_ALVO pra "ontem" (America/Sao_Paulo) quando rodar
    #    via agendamento (schedule), sem input manual.
    TRECHO_MAIN_ANTIGO = '''    dias_alvo_str = os.environ.get("DIAS_ALVO", "")
    if not dias_alvo_str:
        print("::error::Defina a variável de ambiente DIAS_ALVO (ex: 2026-07-16,2026-07-17)")
        sys.exit(1)'''

    TRECHO_MAIN_NOVO = '''    dias_alvo_str = os.environ.get("DIAS_ALVO", "")
    if not dias_alvo_str:
        # Rodando via agendamento (schedule), sem input manual: usa "ontem"
        # no fuso de Canoinhas/Três Barras, que costuma ser o último dia já
        # fechado no Data Much.
        ontem = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).date()
        dias_alvo_str = ontem.strftime("%Y-%m-%d")
        print(f"DIAS_ALVO não veio definido (provável run agendado) — usando ontem: {dias_alvo_str}")'''

    texto = aplicar(texto, TRECHO_MAIN_ANTIGO, TRECHO_MAIN_NOVO, "default DIAS_ALVO = ontem")

    SCRIPT_PATH.write_text(texto, encoding="utf-8")
    print(f"Gravado {SCRIPT_PATH}")


if __name__ == "__main__":
    main()
