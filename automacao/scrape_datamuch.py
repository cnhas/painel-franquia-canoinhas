"""
Scraper de contexto mensal — Data Much (Canoinhas/Três Barras)

FASE 1 (este script): detecta quando um novo dia fecha no Data Much e atualiza:
  - contexto_mensal (GMV do mês, projeção, meta, acumulado do ano — versões GMV e Pedidos)
  - gmv_diario_mes (adiciona o dia novo fechado)
  - data_much_status (timestamps de verificação)

NÃO atualiza ainda (fase 2, futura): cupons, ofertas De/Por, ranking de lojas,
investimentos. Essas partes continuam manuais por enquanto.

Estrutura do site (confirmada manualmente em 17/07/2026, mas pode mudar):
  - Login: https://datamuch.deliverymuch.com.br/login — formulário simples, FORA de
    iframe. Campo com placeholder "E-mail", campo com placeholder "Senha", botão "Entrar".
  - Relatório: https://datamuch.deliverymuch.com.br/app/report/208 — o conteúdo real
    (cards, gráficos) fica DENTRO de um <iframe> (embed tipo Zoho Analytics/Reports).
    Isso significa que no Playwright é preciso usar page.frame_locator("iframe") pra
    alcançar os elementos — page.locator(...) direto não encontra nada lá dentro.
  - Tem dois botões toggle "GMV" / "Pedidos" que trocam as métricas mostradas nos cards
    (mesma UI, dados diferentes).
  - Um texto "Última Atualização" + data/hora (ex: "16/07/2026 08:54:57") no canto
    superior direito indica quando o Data Much processou os dados pela última vez —
    esse é o gatilho pra saber se apareceu um dia novo fechado.
  - 5 cards horizontais com métricas: GMV | Média GMV/Dia | GMV Projetado | Meta |
    Acumulado. Sub-rótulos observados: "Realizado", "% MoM", "% YoY", "Meta até ontem",
    "% Realizado até ontem", "GMV ano anterior". ATENÇÃO: alguns rótulos se repetem em
    mais de um card (ex: "Realizado" aparece no card GMV E no card Média GMV/Dia), então
    a extração usa índice posicional (ordem visual esquerda→direita) — se o layout do
    site mudar, isso pode quebrar e vai precisar ajustar via captura de tela real.

IMPORTANTE: este script é a primeira versão, escrita sem conseguir inspecionar o DOM
bruto do iframe (ferramentas de inspeção de acessibilidade não alcançam iframes de
outra origem). Espera-se precisar de mais de uma rodada de ajuste de seletores
comparando com screenshots reais tiradas em execuções que falharem (mesmo processo
usado pra depurar o scrape_pedidos.py).

Requisitos: pip install playwright && playwright install chromium
Variáveis de ambiente: DATAMUCH_EMAIL, DATAMUCH_SENHA

Saída: escreve "mudou=true" ou "mudou=false" no arquivo apontado por $GITHUB_OUTPUT,
pro workflow decidir se vale a pena rodar o deploy/commit (economiza tempo/custo nas
execuções em que o Data Much ainda não atualizou nada novo).
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DATAMUCH_URL_LOGIN = "https://datamuch.deliverymuch.com.br/login"
DATAMUCH_URL_RELATORIO = "https://datamuch.deliverymuch.com.br/app/report/208"

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

BR_TZ = timezone(timedelta(hours=-3))
NAV_TIMEOUT_MS = 45000


def escrever_output(nome: str, valor: str):
    caminho = os.environ.get("GITHUB_OUTPUT")
    if caminho:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"{nome}={valor}\n")
    print(f"[output] {nome}={valor}")


def parse_valor_brl(texto: str) -> float:
    limpo = re.sub(r"[^\d,.\-]", "", texto)
    limpo = limpo.replace(".", "").replace(",", ".")
    if limpo in ("", "-", "."):
        return 0.0
    return float(limpo)


def parse_pct(texto: str) -> float:
    limpo = texto.replace("%", "").replace(",", ".").strip()
    return float(limpo)


def login_datamuch(page):
    page.goto(DATAMUCH_URL_LOGIN, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    email = os.environ["DATAMUCH_EMAIL"]
    senha = os.environ["DATAMUCH_SENHA"]
    page.get_by_placeholder("E-mail").fill(email)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=NAV_TIMEOUT_MS)


def obter_frame_relatorio(page):
    page.goto(DATAMUCH_URL_RELATORIO, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    frame = page.frame_locator("iframe").first
    # O embed é um relatório do Power BI (confirmado via diagnóstico real: iframe src =
    # app.powerbi.com/reportEmbed) — demora mais que uma página normal pra carregar e
    # calcular, principalmente numa sessão nova/fria — timeout bem mais generoso que o
    # resto do script.
    frame.get_by_text(re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")).first.wait_for(
        state="visible", timeout=90000
    )
    return frame


def ler_ultima_atualizacao(frame) -> datetime:
    # Power BI renderiza esse texto via SVG — Locator.inner_text() direto no nó específico
    # falha com "Node is not an HTMLElement" (confirmado via execução real). Em vez de
    # tentar ler o nó exato, pega o texto inteiro do <body> do iframe (isso funciona,
    # <body> é um HTMLElement de verdade) e extrai a data por regex — mesma técnica
    # robusta usada em ler_cards_mensais().
    texto_completo = frame.locator("body").inner_text()
    m = re.search(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}", texto_completo)
    if not m:
        raise RuntimeError(
            f"Não achei o texto de 'Última Atualização' na página. Texto: {texto_completo[:500]!r}"
        )
    return datetime.strptime(m.group(0), "%d/%m/%Y %H:%M:%S")


def clicar_toggle(frame, rotulo: str):
    # Confirmado via log de falha real (execução automática de 18/07/2026, 07:31): esse
    # toggle "GMV"/"Pedidos" do Power BI NÃO tem role="button" com nome acessível — é o
    # mesmo problema já visto em ler_ultima_atualizacao (texto renderizado sem semântica
    # de HTML normal). get_by_role("button", ...) nunca resolvia e só dava timeout de
    # 45s. Texto puro capturado no diagnóstico confirma "Pedidos" e "GMV" aparecem como
    # linhas isoladas de texto (mesmo padrão do link "Hoje" no scrape_pedidos.py) — troca
    # pra get_by_text exato, com .first pro caso de "GMV" aparecer de novo mais abaixo
    # (no card de resultado).
    frame.get_by_text(rotulo, exact=True).first.click(timeout=NAV_TIMEOUT_MS)
    frame.get_by_text(re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")).first.wait_for(
        state="visible", timeout=NAV_TIMEOUT_MS
    )


def ler_cards_mensais(frame) -> dict:
    """Lê os 5 cards de métricas por POSIÇÃO (não por rótulo de texto), já que vários
    rótulos se repetem entre cards (ex: 'Realizado' aparece em 2 cards, '% YoY' em 3).
    Ordem confirmada visualmente em 17/07/2026 (screenshot real), esquerda->direita:

      [GMV]            R$ valor / "Realizado" / pct "% MoM" / pct "% YoY"
      [Média GMV/Dia]  R$ valor / "Realizado" / pct "% MoM" / pct "% YoY"
      [GMV Projetado]  R$ valor / "GMV Projetado" / pct "% MoM" / pct "% YoY"
      [Meta]           R$ valor / "Meta" / R$ valor "Meta até ontem" / pct "% Realizado até ontem"
      [Acumulado]      R$ valor / "GMV até ontem" / R$ valor "GMV ano anterior" / pct "% YoY"

    Ou seja, em ordem: 7 valores "principais" e 8 percentuais. Extrai tudo de uma vez via
    regex sobre o texto puro da região dos cards (mais robusto que tentar mapear rótulo
    por rótulo, que falha quando o texto se repete).

    IMPORTANTE (descoberto via execução real de 20/07/2026, testando a visão "Pedidos"
    pela primeira vez): na visão GMV os 7 valores principais vêm como "R$ 1.234,56", mas
    na visão PEDIDOS os mesmos 7 valores vêm como números simples "4.152" / "218" (sem
    "R$", já que são contagem de pedidos, não dinheiro) — então a regex de R$ sozinha
    achava 0 valores e a função quebrava. Corrigido pra: 1) cortar o texto ANTES de
    "Resultados" também (não só depois de "Meta do Mês"), removendo o texto de filtros/
    data do topo que também tem números soltos e poderia contaminar a extração da visão
    Pedidos; 2) se não achar "R$", cair pro formato de número simples (com separador de
    milhar brasileiro) nos números que sobram depois de remover os percentuais."""
    texto_completo = frame.locator("body").inner_text()
    # "Resultados" aparece logo antes dos cards em ambas as visões — corta antes disso pra
    # não pegar números soltos do cabeçalho (data de "Última Atualização", filtros).
    corte = texto_completo.split("Resultados", 1)[-1]
    # Corta antes de "Meta do Mês" (o gráfico de velocímetro logo abaixo dos cards também
    # tem números que atrapalhariam a extração se fossem incluídos).
    corte = corte.split("Meta do Mês")[0]
    valores_pct = [parse_pct(v) for v in re.findall(r"-?[\d.,]+\s?%", corte)]

    valores_rs_str = re.findall(r"-?R\$\s?[\d.,]+", corte)
    if valores_rs_str:
        valores_rs = [parse_valor_brl(v) for v in valores_rs_str]
    else:
        # Visão Pedidos: sem "R$". Remove os percentuais do texto primeiro (pra não
        # confundir "4,6%" com um valor principal) e extrai os números simples restantes.
        sem_pct = re.sub(r"-?[\d.,]+\s?%", "", corte)
        valores_rs = [parse_valor_brl(v) for v in re.findall(r"-?\d[\d.]*\d|-?\d", sem_pct)]

    if len(valores_rs) < 7 or len(valores_pct) < 8:
        raise RuntimeError(
            f"Esperava >=7 valores principais e >=8 percentuais nos cards, achei "
            f"{len(valores_rs)} e {len(valores_pct)}. Texto lido: {corte[:1000]!r}"
        )
    return {
        "realizado_mes": valores_rs[0],
        "mom_pct": valores_pct[0],
        "yoy_pct": valores_pct[1],
        "media_dia": valores_rs[1],
        "projetado_mes": valores_rs[2],
        "meta_mes": valores_rs[3],
        "meta_ate_ontem": valores_rs[4],
        "pct_realizado_ate_ontem": valores_pct[6],
        "acumulado_ano": valores_rs[5],
        "ano_anterior": valores_rs[6],
        "yoy_ano_pct": valores_pct[7],
    }


def coletar_contexto(frame) -> dict:
    """Coleta os campos de contexto_mensal, primeiro na visão GMV, depois trocando pra
    visão Pedidos."""
    gmv = ler_cards_mensais(frame)

    # --- Troca pra visão Pedidos ---
    clicar_toggle(frame, "Pedidos")
    pedidos = ler_cards_mensais(frame)
    # Volta pra visão GMV (deixa a UI como estava, por precaução).
    clicar_toggle(frame, "GMV")

    return {
        "mes_referencia": datetime.now(BR_TZ).strftime("%Y-%m"),
        "atualizado_em": datetime.now(BR_TZ).strftime("%Y-%m-%dT%H:%M:%S"),
        "gmv_realizado_mes": round(gmv["realizado_mes"], 2),
        "gmv_mom_pct": gmv["mom_pct"],
        "gmv_yoy_pct": gmv["yoy_pct"],
        "media_gmv_dia": round(gmv["media_dia"], 2),
        "gmv_projetado_mes": round(gmv["projetado_mes"]),
        "meta_mes": round(gmv["meta_mes"]),
        "meta_ate_ontem": round(gmv["meta_ate_ontem"]),
        "pct_realizado_ate_ontem": gmv["pct_realizado_ate_ontem"],
        "gmv_acumulado_ano": round(gmv["acumulado_ano"], 2),
        "gmv_ate_ontem_ano": round(gmv["ano_anterior"], 2),
        "gmv_yoy_ano_pct": gmv["yoy_ano_pct"],
        "pedidos_realizado_mes": int(pedidos["realizado_mes"]),
        "media_pedidos_dia": int(pedidos["media_dia"]),
        "pedidos_projetado_mes": int(pedidos["projetado_mes"]),
        "meta_pedidos_mes": int(pedidos["meta_mes"]),
        "meta_pedidos_ate_ontem": int(pedidos["meta_ate_ontem"]),
        "pct_pedidos_realizado_ate_ontem": pedidos["pct_realizado_ate_ontem"],
        "pedidos_acumulado_ano": int(pedidos["acumulado_ano"]),
        "pedidos_yoy_ano_pct": pedidos["yoy_ano_pct"],
    }


def atualizar_gmv_diario(gmv_diario_atual: list, novo_contexto: dict) -> list:
    """Calcula o(s) dia(s) novo(s) fechado(s) por diferença: GMV do mês (novo total)
    menos a soma do que já estava registrado = GMV do(s) dia(s) que faltavam.
    Meta diária é aproximada (meta do mês / dias no mês) já que o Data Much não expõe
    a meta exata de cada dia nessa tela — só a meta do mês inteiro."""
    if not gmv_diario_atual:
        return gmv_diario_atual

    soma_atual = sum(d["gmv"] for d in gmv_diario_atual)
    delta = round(novo_contexto["gmv_realizado_mes"] - soma_atual, 2)
    if delta <= 0:
        return gmv_diario_atual  # nada novo pra adicionar (ou até diminuiu — não mexe)

    ultimo_dia = datetime.strptime(gmv_diario_atual[-1]["data"], "%Y-%m-%d")
    novo_dia = ultimo_dia + timedelta(days=1)

    ano, mes = novo_dia.year, novo_dia.month
    dias_no_mes = (datetime(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)).day
    meta_diaria_aprox = round(novo_contexto["meta_mes"] / dias_no_mes)

    gmv_diario_atual = [d for d in gmv_diario_atual if not d.get("parcial")]
    gmv_diario_atual.append({
        "data": novo_dia.strftime("%Y-%m-%d"),
        "gmv": delta,
        "meta": meta_diaria_aprox,
    })
    return gmv_diario_atual


def substituir_bloco_objeto(texto: str, chave: str, novo_valor_json: str) -> str:
    padrao = rf'"{chave}":\s*\{{[^{{}}]*\}}'
    return re.sub(padrao, f'"{chave}": {novo_valor_json}', texto, count=1, flags=re.DOTALL)


def substituir_bloco_array(texto: str, chave: str, novo_valor_json: str) -> str:
    padrao = rf'"{chave}":\s*\[[^\[\]]*\]'
    return re.sub(padrao, f'"{chave}": {novo_valor_json}', texto, count=1, flags=re.DOTALL)


def atualizar_arquivos(novo_contexto: dict, gmv_diario_novo: list, data_datamuch: datetime, novo_dia_detectado: bool):
    agora = datetime.now(BR_TZ)
    novo_status = {
        "dashboard_url": "https://datamuch.deliverymuch.com.br/app/report/208",
        "ultima_atualizacao_conhecida": data_datamuch.strftime("%d/%m/%Y %H:%M:%S"),
        "verificado_em": agora.strftime("%d/%m/%Y %H:%M"),
        "novo_dia_detectado": novo_dia_detectado,
        # Data em que confirmamos a atualização de hoje — usado pelo pre-check
        # (verificar_datamuch_ok.py) pra pular as próximas checagens do mesmo dia, já
        # que o Data Much só atualiza 1x por dia.
        "verificado_ok_data": agora.strftime("%Y-%m-%d"),
    }

    contexto_json = json.dumps(novo_contexto, ensure_ascii=False, indent=2)
    gmv_diario_json = json.dumps(gmv_diario_novo, ensure_ascii=False)
    status_json = json.dumps(novo_status, ensure_ascii=False, indent=2)

    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto = substituir_bloco_objeto(texto, "contexto_mensal", contexto_json)
        texto = substituir_bloco_array(texto, "gmv_diario_mes", gmv_diario_json)
        texto = substituir_bloco_objeto(texto, "data_much_status", status_json)
        path.write_text(texto, encoding="utf-8")
        print(f"Atualizado: {path}")


def _diagnosticar_erro(page):
    """Salva screenshot + informações de diagnóstico quando algo dá errado — sem isso é
    impossível saber o que aconteceu de verdade numa execução do GitHub Actions (não tem
    como abrir o navegador remotamente pra ver)."""
    try:
        page.screenshot(path="erro_pagina_principal.png", full_page=True)
    except Exception as e:
        print(f"(não consegui tirar screenshot da página principal: {e})")

    try:
        print(f"URL atual: {page.url}")
        print(f"Título da página: {page.title()}")
        iframes = page.query_selector_all("iframe")
        print(f"Quantidade de <iframe> na página: {len(iframes)}")
        for i, el in enumerate(iframes):
            try:
                src = el.get_attribute("src") or "(sem src)"
                # Corta a URL pra não vazar token/query string nos logs.
                src_curto = src.split("?")[0]
                box = el.bounding_box()
                print(f"  iframe[{i}]: src={src_curto} bounding_box={box}")
            except Exception as e:
                print(f"  iframe[{i}]: erro ao inspecionar ({e})")
        # Tenta printar o texto visível da página principal (fora do iframe) — pode
        # revelar uma mensagem de erro, banner de cookie, ou tela de acesso negado.
        texto_pagina = page.locator("body").inner_text()[:1500]
        print(f"Texto da página principal (primeiros 1500 chars): {texto_pagina!r}")
    except Exception as e:
        print(f"(diagnóstico extra falhou: {e})")

    try:
        frame = page.frame_locator("iframe").first
        frame.locator("body").screenshot(path="erro_iframe.png", timeout=5000)
    except Exception as e:
        print(f"(não consegui tirar screenshot do conteúdo do iframe: {e})")

    try:
        frame = page.frame_locator("iframe").first
        texto_frame = frame.locator("body").inner_text(timeout=5000)[:1500]
        print(f"Texto dentro do iframe (primeiros 1500 chars): {texto_frame!r}")
    except Exception as e:
        print(f"(não consegui ler texto de dentro do iframe: {e})")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # IMPORTANTE: o relatório é um embed do Power BI, e o Power BI formata datas e
        # números de acordo com o locale do navegador. Descoberto via execução real:
        # sem isso, uma sessão nova do Chromium (locale padrão en-US) mostra
        # "7/16/2026 8:54:57 AM" e "R$ 226,249.15" em vez de "16/07/2026 08:54:57" e
        # "R$ 226.249,15" — quebrando todos os regex escritos pro formato brasileiro.
        context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            login_datamuch(page)
            frame = obter_frame_relatorio(page)
            data_datamuch = ler_ultima_atualizacao(frame)

            historico_atual = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
            ultima_conhecida_str = historico_atual.get("data_much_status", {}).get(
                "ultima_atualizacao_conhecida", ""
            )
            ja_conhecida = False
            if ultima_conhecida_str:
                try:
                    ultima_conhecida = datetime.strptime(ultima_conhecida_str, "%d/%m/%Y %H:%M:%S")
                    ja_conhecida = data_datamuch <= ultima_conhecida
                except ValueError:
                    pass

            if ja_conhecida:
                print(f"Sem novidade no Data Much (última atualização lá: {data_datamuch}).")
                # Mesmo sem mudança de dados, registra que checamos — só localmente nos 2
                # arquivos (não vale a pena commitar/deployar só por isso; o workflow não
                # roda os passos de deploy/commit quando mudou=false, então essa escrita
                # fica só na cópia local do runner, descartada no final do job).
                status = historico_atual.get("data_much_status", {})
                status["verificado_em"] = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
                status_json = json.dumps(status, ensure_ascii=False, indent=2)
                for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
                    if path.exists():
                        texto = path.read_text(encoding="utf-8")
                        texto = substituir_bloco_objeto(texto, "data_much_status", status_json)
                        path.write_text(texto, encoding="utf-8")
                escrever_output("mudou", "false")
                return

            print(f"Novidade encontrada no Data Much! Última atualização lá: {data_datamuch}")
            novo_contexto = coletar_contexto(frame)
            gmv_diario_novo = atualizar_gmv_diario(historico_atual.get("gmv_diario_mes", []), novo_contexto)
            atualizar_arquivos(novo_contexto, gmv_diario_novo, data_datamuch, novo_dia_detectado=True)
            escrever_output("mudou", "true")

        except PlaywrightTimeoutError as e:
            print(f"::error::Timeout esperando elemento — provavelmente um seletor mudou: {e}")
            _diagnosticar_erro(page)
            escrever_output("mudou", "false")
            sys.exit(1)
        except RuntimeError as e:
            print(f"::error::{e}")
            _diagnosticar_erro(page)
            escrever_output("mudou", "false")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
