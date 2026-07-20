"""
Scraper de detalhe DIÁRIO — Data Much (Canoinhas/Três Barras)

FASE 2 (este script): pra um dia específico já fechado no Data Much, coleta o
detalhe completo que o painel mostra em "ver o dia" e escreve/atualiza a entrada
correspondente no array `dias[]` de index.html e historico_vendas.json:

  - Top 10 lojas por GMV e por pedidos (relatório "Acompanhamento de Lojas", /app/report/488)
  - Uso de cupons, cupons por categoria, e métricas de cupom (relatório
    "Acompanhamento de Cupons", /app/report/216)
  - Ofertas De/Por: itens vendidos, GMV produtos, subsídios (relatório
    "Ofertas De/Por", /app/report/434)

NÃO coleta (por enquanto): dados do Painel (pedidos_totais/cancelados/entrega/
retirada) — isso vem de um site totalmente diferente (panel.deliverymuch.com.br,
já tratado em scrape_pedidos.py) e fica de fora desta primeira versão pra não
inflar ainda mais o escopo. O campo "painel" da entrada do dia fica ausente
quando este script cria/atualiza a entrada — dá pra completar numa próxima
rodada.

DESCOBERTA IMPORTANTE (sessão de 20/07/2026, validada manualmente comparando
com os dados já salvos do dia 15/07 — bateram exato, centavo a centavo, nos 3
relatórios): os 3 relatórios abaixo, quando filtrados pra um único dia (campo
"Data" do painel de filtro = mesma data de início e fim), mostram exatamente
os valores de UM dia:

  - /app/report/488 "Acompanhamento de Lojas", aba "Geral": tabela com colunas
    UF/cidade/empresa/.../"gmv (mês atual)"/"pedidos (mês atual)"/etc. Apesar do
    nome da coluna dizer "mês atual", na prática ela reflete o filtro de Data
    aplicado. Clicar no cabeçalho da coluna "gmv (mês atual)" ordena por esse
    valor (2 cliques = decrescente, no teste manual). Top 10 dessa ordenação =
    top_lojas_gmv. Repetir ordenando pela coluna de pedidos = top_lojas_pedidos.

  - /app/report/216 "Acompanhamento de Cupons": mesmo filtro de Data, os cards
    do topo (Pedidos, GMV, Desconto Total, Ticket Médio, GMV/Cupom, Lojas
    Únicas) mapeiam direto pra pedidos_cupom/gmv_cupom/desconto_total/
    ticket_medio_cupom/gmv_por_cupom/lojas_unicas_cupom. Os gráficos "Cupons
    por categoria" e "Uso de Cupons" dão cupons_categoria[] e cupons_uso[].

  - /app/report/434 "Ofertas De/Por": mesmo filtro de Data, os 4 cards do topo
    (Itens, Subsídio DM, Subsídio Franquia, Subsídio Loja, GMV Produtos) —
    ATENÇÃO: só tem esses 4-5 cards, sem "destaques" (produtos mais vendidos);
    esse campo fica como lista vazia nesta versão.

TODOS os 3 relatórios usam o mesmo padrão de filtro (confirmado manualmente):
  1. Um ícone de funil na barra lateral esquerda do relatório, com atributo
     title="Abrir opções de filtro", abre um painel de filtros.
  2. Dentro do painel, um campo "Data" com dois textos no formato dd/mm/aaaa
     (início e fim do intervalo) — clicar em qualquer um abre um calendário
     mensal (dom/seg/ter/.../sáb, com um cabeçalho "mês aaaa" e setas
     prev/próximo mês).
  3. Clicar no número do dia desejado seleciona aquela data.
  4. Repetir pro segundo campo (fim) com o MESMO dia — assim o intervalo vira
     um único dia.
  5. Fechar o painel (ícone "X") aplica o filtro (não tem botão "Aplicar"
     separado — confirmado, os cards já atualizam sozinhos assim que os dois
     campos têm valor).

IMPORTANTE — este script foi escrito SEM conseguir inspecionar o DOM bruto de
dentro do iframe (os relatórios são embeds cross-origin; nem accessibility tree
nem `iframe.contentDocument` alcançam o conteúdo — só Playwright via
frame_locator, que opera em nível de CDP e ignora a restrição de mesma
origem). Os seletores de texto usados aqui foram desenhados a partir de
observação visual real (screenshots), não de inspeção de DOM — é esperado
precisar de pelo menos uma rodada de ajuste depois de rodar de verdade e
revisar os screenshots de diagnóstico salvos em caso de erro (mesmo processo
já usado pros outros scrapers deste projeto).

Requisitos: pip install playwright && playwright install chromium
Variáveis de ambiente: DATAMUCH_EMAIL, DATAMUCH_SENHA
Argumento: uma ou mais datas YYYY-MM-DD (separadas por vírgula) na variável de
ambiente DIAS_ALVO, ex: DIAS_ALVO=2026-07-16,2026-07-17,2026-07-18,2026-07-19
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Frame

DATAMUCH_URL_LOGIN = "https://datamuch.deliverymuch.com.br/login"
URL_LOJAS = "https://datamuch.deliverymuch.com.br/app/report/488"
URL_CUPONS = "https://datamuch.deliverymuch.com.br/app/report/216"
URL_OFERTAS = "https://datamuch.deliverymuch.com.br/app/report/434"

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

NAV_TIMEOUT_MS = 45000

MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def parse_valor_brl(texto: str) -> float:
    limpo = re.sub(r"[^\d,.\-]", "", texto)
    limpo = limpo.replace(".", "").replace(",", ".")
    if limpo in ("", "-", "."):
        return 0.0
    return float(limpo)


def login_datamuch(page):
    page.goto(DATAMUCH_URL_LOGIN, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    email = os.environ["DATAMUCH_EMAIL"]
    senha = os.environ["DATAMUCH_SENHA"]
    page.get_by_placeholder("E-mail").fill(email)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=NAV_TIMEOUT_MS)


def obter_frame(page, url: str) -> Frame:
    page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    frame = page.frame_locator("iframe").first
    # Espera algo renderizar de verdade dentro do iframe antes de seguir.
    frame.locator("body").wait_for(state="visible", timeout=60000)
    page.wait_for_timeout(2000)
    return frame


def _esperar(frame, ms: int):
    """FrameLocator não tem wait_for_timeout (só Page/Frame têm) — pega a Page
    dona do frame via um Locator qualquer dentro dele e espera por ali."""
    frame.locator("body").page.wait_for_timeout(ms)


def abrir_painel_filtro(frame):
    # DESCOBERTA (execução real de 20/07/2026): estes relatórios (Lojas/Cupons/
    # Ofertas), apesar de terem sido registrados numa sessão anterior como "não
    # são Power BI" (só o report/208 seria), na verdade TAMBÉM são embeds do
    # Power BI — confirmado pelo texto "Relatório do Power BI" capturado no
    # diagnóstico de erro. Isso significa que ícones como o funil de filtro
    # quase certamente NÃO têm atributo HTML "title" (mesmo problema já visto
    # com "Última Atualização" e os toggles GMV/Pedidos no report/208) — o
    # seletor por título falhou com timeout. Tenta várias estratégias em
    # sequência: role=button com nome acessível, aria-label, e por último
    # title (caso algum dos 3 relatórios seja diferente do 208).
    estrategias = [
        lambda: frame.get_by_role("button", name=re.compile("filtro", re.I)).first,
        lambda: frame.locator('[aria-label*="iltro"]').first,
        lambda: frame.locator('[title*="iltro"]').first,
    ]
    ultimo_erro = None
    for estrategia in estrategias:
        try:
            el = estrategia()
            el.click(timeout=15000)
            frame.get_by_text("Data", exact=True).first.wait_for(state="visible", timeout=10000)
            return
        except Exception as e:
            ultimo_erro = e
            continue
    raise RuntimeError(f"Não consegui abrir o painel de filtro por nenhuma estratégia. Último erro: {ultimo_erro}")


def _fechar_overlay_calendario(frame):
    """Se preencher o campo de data abriu um calendário overlay por cima da
    tela (confirmado via erro real: um <div class="cdk-overlay-backdrop">
    passa a interceptar cliques em qualquer outro elemento), fecha com
    Escape. Não é erro se não tiver nada pra fechar."""
    try:
        pagina = frame.locator("body").page
        pagina.keyboard.press("Escape")
    except Exception:
        pass


def selecionar_dia_unico(frame, dia: date):
    """Abre o painel de filtro (se ainda não estiver aberto) e seleciona o campo
    Data pra cobrir só o dia indicado (início = fim = dia).

    DESCOBERTA (execução real de 20/07/2026, via dump de aria-labels no
    diagnóstico de erro): os campos de data do filtro NÃO são spans de texto
    clicáveis que abrem um calendário visual pra clicar no dia — são inputs de
    verdade com aria-label "Data de início. Intervalo de entrada disponível
    ..." e "Data de término. Intervalo de entrada disponível ...". Dá pra
    preencher direto com .fill(), sem precisar navegar calendário nenhum —
    bem mais simples e confiável."""
    abrir_painel_filtro(frame)

    data_str = dia.strftime("%d/%m/%Y")
    campo_inicio = frame.get_by_label(re.compile("Data de início", re.I)).first
    campo_fim = frame.get_by_label(re.compile(r"Data de t[ée]rmino", re.I)).first

    # NÃO clica no campo antes de preencher — clicar abre um calendário
    # (overlay do Angular Material/CDK) por cima da tela, que fica bloqueando
    # cliques nos elementos seguintes (confirmado via erro real: "cdk-overlay-
    # backdrop ... intercepts pointer events"). .fill() já foca o campo
    # sozinho, sem abrir esse overlay.
    campo_inicio.fill(data_str)
    campo_inicio.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 500)

    campo_fim.fill(data_str)
    campo_fim.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 1500)

    # Fecha o painel de filtro. Confirmado que não existe botão "Aplicar"
    # separado (os cards já reagem assim que os 2 campos têm valor) — então
    # só precisa tirar o painel da frente. Tenta clicar num ícone de fechar
    # por algumas estratégias e, se nenhuma funcionar, tenta Escape; se nem
    # isso fechar o painel, não é necessariamente um problema — os cards por
    # trás já devem ter atualizado, só ficam parcialmente cobertos pelo
    # painel na leitura via inner_text (que não se importa com sobreposição
    # visual, então não deveria atrapalhar a extração de texto).
    for estrategia in (
        lambda: frame.get_by_role("button", name=re.compile("fechar", re.I)).first,
        lambda: frame.locator('[aria-label*="echar" i]').first,
        lambda: frame.locator('[title*="echar" i]').first,
    ):
        try:
            estrategia().click(timeout=5000)
            break
        except Exception:
            continue
    else:
        try:
            frame.locator("body").press("Escape")
        except Exception:
            pass
    _esperar(frame, 1500)


def ler_cards_ofertas(frame) -> dict:
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_itens = re.search(r"(\d[\d.]*)\s*\n?\s*Itens", texto)
        m_dm = re.search(r"R\$\s?([\d.,]+)\s*(Mil)?\s*\n?\s*Subsídio DM", texto)
        m_franquia = re.search(r"R\$\s?([\d.,]+)\s*(Mil)?\s*\n?\s*Subsídio Franquia", texto)
        m_loja = re.search(r"R\$\s?([\d.,]+)\s*(Mil)?\s*\n?\s*Subsídio Loja", texto)
        m_gmv = re.search(r"R\$\s?([\d.,]+)\s*(Mil)?\s*\n?\s*GMV Produtos", texto)
        if m_itens and m_dm and m_franquia and m_loja and m_gmv:
            def valor(m):
                v = parse_valor_brl(m.group(1))
                if m.group(2):  # "Mil"
                    v *= 1000
                return v
            return {
                "itens_vendidos": int(parse_valor_brl(m_itens.group(1))),
                "subsidio_dm": round(valor(m_dm), 2),
                "subsidio_franquia": round(valor(m_franquia), 2),
                "subsidio_loja": round(valor(m_loja), 2),
                "gmv_produtos": round(valor(m_gmv), 2),
                "destaques": [],
            }
        if time.monotonic() >= limite:
            raise RuntimeError(f"Não achei os cards de Ofertas De/Por. Texto: {texto[:1500]!r}")
        _esperar(frame, 500)


def ler_cards_cupons(frame) -> dict:
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_pedidos = re.search(r"(\d[\d.]*)\s*\n?\s*Pedidos\b", texto)
        m_gmv = re.search(r"R\$\s?([\d.,]+)\s*\n?\s*GMV(?!/)\b", texto)  # (?!/) evita casar com o card "GMV/Cupom"
        m_desconto = re.search(r"R\$\s?([\d.,]+)\s*\n?\s*Desconto Total", texto)
        m_ticket = re.search(r"R\$\s?([\d.,]+)\s*\n?\s*Ticket Médio", texto)
        m_gmv_cupom = re.search(r"R\$\s?([\d.,]+)\s*\n?\s*GMV/Cupom", texto)
        m_lojas = re.search(r"(\d[\d.]*)\s*\n?\s*Lojas Únicas", texto)
        if m_pedidos and m_gmv and m_desconto and m_ticket and m_gmv_cupom and m_lojas:
            break
        if time.monotonic() >= limite:
            raise RuntimeError(f"Não achei os cards de Cupons. Texto: {texto[:1500]!r}")
        _esperar(frame, 500)

    # "Cupons por categoria": pares "Nome da categoria" + número, na ordem em
    # que aparecem no gráfico de barras horizontal.
    categorias = []
    bloco_cat_match = re.search(
        r"Cupons por categoria(.*?)Contagem de coupon_code", texto, re.DOTALL
    )
    print(f"[debug ler_cards_cupons] bloco categoria achado: {bool(bloco_cat_match)}")
    if bloco_cat_match:
        linhas = [l.strip() for l in bloco_cat_match.group(1).split("\n") if l.strip()]
        print(f"[debug ler_cards_cupons] linhas bloco categoria ({len(linhas)}): {linhas!r}")
        i = 0
        while i < len(linhas) - 1:
            if re.match(r"^[\d.,]+$", linhas[i + 1]):
                categorias.append({
                    "categoria": linhas[i],
                    "qtd": int(parse_valor_brl(linhas[i + 1])),
                })
                i += 2
            else:
                i += 1

    # "Uso de Cupons": mesmo padrão "CÓDIGO" + número, no gráfico "Pedidos Total".
    usos = []
    bloco_uso_match = re.search(r"Uso de Cupons(.*?)Pedidos Total", texto, re.DOTALL)
    print(f"[debug ler_cards_cupons] bloco uso achado: {bool(bloco_uso_match)}")
    if bloco_uso_match:
        linhas = [l.strip() for l in bloco_uso_match.group(1).split("\n") if l.strip()]
        print(f"[debug ler_cards_cupons] linhas bloco uso ({len(linhas)}): {linhas!r}")
        i = 0
        while i < len(linhas) - 1:
            if re.match(r"^[\d.,]+$", linhas[i + 1]):
                usos.append({
                    "codigo": linhas[i],
                    "pedidos": int(parse_valor_brl(linhas[i + 1])),
                })
                i += 2
            else:
                i += 1

    return {
        "pedidos_cupom": int(parse_valor_brl(m_pedidos.group(1))),
        "gmv_cupom": round(parse_valor_brl(m_gmv.group(1)), 2),
        "desconto_total": round(parse_valor_brl(m_desconto.group(1)), 2),
        "ticket_medio_cupom": round(parse_valor_brl(m_ticket.group(1)), 2),
        "gmv_por_cupom": round(parse_valor_brl(m_gmv_cupom.group(1)), 2),
        "lojas_unicas_cupom": int(parse_valor_brl(m_lojas.group(1))),
        "cupons_categoria": categorias,
        "cupons_uso": usos,
    }


def _extrair_registro_loja(linhas: list):
    """Extrai {nome, gmv, pedidos} de um bloco de linhas de UM registro de
    loja (já dividido no marcador "Selecionar Linha"). Formato real por linha
    (confirmado via diagnóstico de execução real, 20/07/2026 — texto puro de
    dentro do iframe, uma "célula" por linha de texto, exatamente 15 linhas
    por registro de loja, nessa ordem):
      UF, id_cidade, cidade, id_empresa, empresa, status, categoria,
      "R$ gmv atual", "R$ gmv anterior", "pct% mom", "Formatação Condicional
      Adicional", pedidos_atual, pedidos_anterior, "pct% mom",
      "Formatação Condicional Adicional"
    Localiza a posição do status ("Publicada"/"Encerrada") como âncora — mais
    tolerante a variação no nº de linhas do que índice fixo. Categoria e
    valores podem vir como "\xa0" (nbsp) quando vazios/zerados (comum em
    lojas "Encerrada", que legitimamente não têm valor no período filtrado)."""
    idx_status = None
    for i, l in enumerate(linhas):
        if l in ("Publicada", "Encerrada"):
            idx_status = i
            break
    if idx_status is None or idx_status < 1:
        return None
    nome = linhas[idx_status - 1].strip()
    resto = linhas[idx_status + 1:]
    valores_rs = [l for l in resto if l.startswith("R$") or l == "\xa0"]
    gmv_str = valores_rs[0] if len(valores_rs) >= 1 else ""
    pedidos_str = ""
    achou_formatacao = False
    for l in resto:
        if "Formatação" in l:
            achou_formatacao = True
            continue
        if achou_formatacao:
            pedidos_str = l
            break
    if not nome or nome in ("\xa0",):
        return None
    gmv = parse_valor_brl(gmv_str) if gmv_str not in ("", "\xa0") else 0.0
    pedidos = int(parse_valor_brl(pedidos_str)) if pedidos_str not in ("", "\xa0") else 0
    return {"nome": nome, "gmv": round(gmv, 2), "pedidos": pedidos}


def _ler_registros_tabela_lojas(frame) -> list:
    """Lê TODOS os registros de loja atualmente renderizados na tabela
    (independente da ordenação visual atual)."""
    texto = frame.locator("body").inner_text()
    partes = texto.split("Selecionar Linha")
    registros = []
    for parte in partes[1:]:  # partes[0] é tudo antes do 1º marcador (cabeçalho etc)
        linhas = [l for l in parte.split("\n") if l != ""]
        if len(linhas) < 6:
            continue
        reg = _extrair_registro_loja(linhas)
        if reg:
            registros.append(reg)
    return registros


def _ordenar_tabela_lojas(frame, coluna_texto: str, chave: str, max_cliques: int = 5) -> list:
    """Clica no cabeçalho da coluna indicada até a tabela ficar COMPROVADAMENTE
    em ordem decrescente pela coluna pedida — não apenas um número fixo de
    cliques.

    BUG REAL encontrado e corrigido em 20/07/2026: a versão anterior clicava
    3 vezes às cegas (sem checar nada) e às vezes deixava a tabela ordenada
    errado — ex. o dia 19/07 ficou com um monte de lojas "Encerrada" (que
    legitimamente têm gmv/pedidos vazios no período filtrado) no topo da
    lista visível, gerando um "top 10" todo zerado. Agora confirma lendo e
    comparando os valores reais extraídos depois de cada clique: só considera
    "decrescente de verdade" quando o 1º valor é positivo e os primeiros
    valores estão em ordem não-crescente."""
    cabecalho = frame.get_by_text(coluna_texto, exact=False).first
    ultima_leitura = []
    for tentativa in range(max_cliques):
        registros = _ler_registros_tabela_lojas(frame)
        ultima_leitura = registros
        valores = [r[chave] for r in registros[:5]]
        if valores and valores[0] > 0 and valores == sorted(valores, reverse=True):
            print(f"[debug _ordenar_tabela_lojas/{coluna_texto}] ordenação confirmada na tentativa {tentativa} (valores: {valores}).")
            return registros
        cabecalho.click(timeout=NAV_TIMEOUT_MS)
        _esperar(frame, 1200)
    print(f"[aviso] não confirmei ordenação decrescente de \"{coluna_texto}\" depois de {max_cliques} cliques; "
          f"vou usar a última leitura e reordenar localmente mesmo assim.")
    return ultima_leitura


def ler_top_lojas(frame, ordenar_por: str, top_n: int = 10) -> list:
    """ordenar_por: 'gmv' ou 'pedidos'. Extrai as top_n lojas da tabela
    "Acompanhamento de Lojas" (aba Geral) já filtrada pro dia, ordenadas
    decrescente pela coluna pedida. Clica no cabeçalho até confirmar
    ordenação real (ver _ordenar_tabela_lojas) e SEMPRE reordena localmente
    pelos valores parseados como garantia extra contra ordenação visual
    errada."""
    coluna_texto = "gmv (mês atual)" if ordenar_por == "gmv" else "pedidos (mês atual)"
    chave = "gmv" if ordenar_por == "gmv" else "pedidos"
    registros = _ordenar_tabela_lojas(frame, coluna_texto, chave)
    registros = [r for r in registros if r["nome"] and r["nome"] != "\xa0"]
    registros.sort(key=lambda r: r[chave], reverse=True)
    print(f"[debug ler_top_lojas/{ordenar_por}] {len(registros)} lojas parseadas; amostra: {registros[:3]!r}")
    return registros[:top_n]


def coletar_dia(page, dia: date) -> dict:
    print(f"--- Coletando detalhe do dia {dia} ---")

    frame_lojas = obter_frame(page, URL_LOJAS)
    selecionar_dia_unico(frame_lojas, dia)
    top_gmv = ler_top_lojas(frame_lojas, "gmv")
    top_pedidos = ler_top_lojas(frame_lojas, "pedidos")
    print(f"Lojas: {len(top_gmv)} no ranking GMV, {len(top_pedidos)} no ranking pedidos.")

    frame_cupons = obter_frame(page, URL_CUPONS)
    selecionar_dia_unico(frame_cupons, dia)
    dados_cupons = ler_cards_cupons(frame_cupons)
    print(f"Cupons: {dados_cupons['pedidos_cupom']} pedidos, GMV R${dados_cupons['gmv_cupom']}.")

    frame_ofertas = obter_frame(page, URL_OFERTAS)
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
    }


def dados_cupons_para_dia(dados_cupons: dict) -> dict:
    d = dict(dados_cupons)
    categoria = d.pop("cupons_categoria")
    uso = d.pop("cupons_uso")
    d["cupons_categoria"] = categoria
    d["cupons_uso"] = uso
    return d


def _buscar_gmv_meta(historico: dict, data_str: str):
    for item in historico.get("gmv_diario_mes", []):
        if item["data"] == data_str:
            return item["gmv"], item["meta"]
    return None, None


def upsert_dia(dias_atual: list, novo_dia: dict) -> list:
    dias_atual = [d for d in dias_atual if d["data"] != novo_dia["data"]]
    dias_atual.append(novo_dia)
    dias_atual.sort(key=lambda d: d["data"])
    return dias_atual


def substituir_bloco_array(texto: str, chave: str, novo_valor_json: str) -> str:
    """IMPORTANTE (bug real encontrado e corrigido em 20/07/2026): a versão
    anterior usava uma regex "[.*?]" (não gulosa) pra achar o array inteiro.
    Isso QUEBRA quando o array tem colchetes aninhados dentro dos itens (como
    "dias", cujos itens têm top_lojas_gmv/top_lojas_pedidos/cupons_uso/
    cupons_categoria, cada um um array próprio) — a regex não gulosa para no
    PRIMEIRO "]" que encontra, que é o fechamento de um array aninhado, não o
    fechamento do array de fora. Isso corrompeu o JSON de verdade (deixou
    conteúdo antigo duplicado/pendurado no meio do arquivo). Corrigido pra
    usar json.JSONDecoder().raw_decode, que entende profundidade de colchetes
    de verdade (incluindo strings com colchetes escapados etc) e devolve o
    índice exato de onde o valor JSON válido termina, mesmo que sobre lixo
    depois."""
    marcador = f'"{chave}":'
    pos_chave = texto.find(marcador)
    if pos_chave == -1:
        raise RuntimeError(f"Não encontrei a chave \"{chave}\" no arquivo.")
    pos_valor_antigo = pos_chave + len(marcador)
    # Pula espaços/quebras de linha até o "[" de abertura.
    i = pos_valor_antigo
    while i < len(texto) and texto[i] in " \n\r\t":
        i += 1
    if i >= len(texto) or texto[i] != "[":
        raise RuntimeError(f"Esperava um array logo depois de \"{chave}\": mas achei {texto[i:i+30]!r}")
    decoder = json.JSONDecoder()
    try:
        _, fim_valor_antigo = decoder.raw_decode(texto, i)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Não consegui decodificar o array antigo de \"{chave}\" pra saber onde ele termina: {e}")
    return texto[:pos_chave] + f'"{chave}": {novo_valor_json}' + texto[fim_valor_antigo:]


def atualizar_arquivos_com_dias(dias_novo: list):
    dias_json = json.dumps(dias_novo, ensure_ascii=False, indent=2)
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto_novo = substituir_bloco_array(texto, "dias", dias_json)
        # TRAVA DE SEGURANÇA (adicionada depois de um bug real que corrompeu o
        # JSON em produção em 20/07/2026): antes de gravar, confirma que o
        # trecho "dias": [...] que acabou de ser escrito é JSON válido de
        # verdade, decodificando ele isoladamente. Pro historico_vendas.json
        # (que é JSON puro do arquivo inteiro) confirma o arquivo inteiro.
        try:
            json.loads(dias_json)  # o pedaço que a gente mesmo gerou
            if path == HISTORICO_JSON_PATH:
                json.loads(texto_novo)  # o arquivo inteiro, só pro JSON puro
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Trava de segurança: o resultado pra {path} não é JSON válido, "
                f"NÃO vou gravar (evita repetir a corrupção de 20/07/2026). Erro: {e}"
            )
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Atualizado: {path}")


def _diagnosticar_erro(page, contexto: str):
    ts = int(time.time())
    try:
        page.screenshot(path=f"erro_dia_{contexto}_{ts}.png", full_page=True)
    except Exception as e:
        print(f"(não consegui tirar screenshot: {e})")
    try:
        frame = page.frame_locator("iframe").first
        frame.locator("body").screenshot(path=f"erro_dia_iframe_{contexto}_{ts}.png", timeout=5000)
    except Exception as e:
        print(f"(não consegui tirar screenshot do iframe: {e})")
    try:
        frame = page.frame_locator("iframe").first
        texto_frame = frame.locator("body").inner_text(timeout=5000)[:3000]
        print(f"Texto dentro do iframe ({contexto}, 3000 primeiros chars): {texto_frame!r}")
    except Exception as e:
        print(f"(não consegui ler texto do iframe: {e})")
    # Dump extra: lista os aria-label e title de TODOS os elementos com esses
    # atributos, e os nomes acessíveis de todo elemento role=button — isso
    # deve revelar o nome real do ícone de filtro se as estratégias de
    # abrir_painel_filtro() falharem de novo.
    try:
        frame = page.frame_locator("iframe").first
        aria_labels = frame.locator("[aria-label]").evaluate_all(
            "els => els.map(e => e.getAttribute('aria-label')).filter((v,i,a) => a.indexOf(v)===i).slice(0, 60)"
        )
        print(f"aria-labels únicos encontrados no iframe ({contexto}): {aria_labels}")
    except Exception as e:
        print(f"(não consegui listar aria-labels: {e})")
    try:
        frame = page.frame_locator("iframe").first
        titles = frame.locator("[title]").evaluate_all(
            "els => els.map(e => e.getAttribute('title')).filter((v,i,a) => a.indexOf(v)===i).slice(0, 60)"
        )
        print(f"atributos title únicos encontrados no iframe ({contexto}): {titles}")
    except Exception as e:
        print(f"(não consegui listar titles: {e})")


def main():
    dias_alvo_str = os.environ.get("DIAS_ALVO", "")
    if not dias_alvo_str:
        print("::error::Defina a variável de ambiente DIAS_ALVO (ex: 2026-07-16,2026-07-17)")
        sys.exit(1)
    dias_alvo = [
        datetime.strptime(d.strip(), "%Y-%m-%d").date()
        for d in dias_alvo_str.split(",") if d.strip()
    ]

    historico_atual = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
    dias_atual = historico_atual.get("dias", [])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            login_datamuch(page)

            algum_sucesso = False
            for dia in dias_alvo:
                try:
                    novo_dia = coletar_dia(page, dia)
                    gmv, meta = _buscar_gmv_meta(historico_atual, novo_dia["data"])
                    if gmv is not None:
                        novo_dia["gmv_dia"] = gmv
                        novo_dia["meta_dia"] = meta
                    dias_atual = upsert_dia(dias_atual, novo_dia)
                    algum_sucesso = True
                except (PlaywrightTimeoutError, RuntimeError) as e:
                    print(f"::error::Falha coletando o dia {dia}: {e}")
                    _diagnosticar_erro(page, str(dia))

            if algum_sucesso:
                atualizar_arquivos_com_dias(dias_atual)
                print("mudou=true")
            else:
                print("::error::Nenhum dia foi coletado com sucesso.")
                sys.exit(1)

        finally:
            browser.close()


if __name__ == "__main__":
    main()
