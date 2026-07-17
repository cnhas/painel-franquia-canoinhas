"""
Scraper de pedidos ao vivo — Painel Delivery Much (Canoinhas/Três Barras)

O que faz:
1. Loga em https://panel.deliverymuch.com.br com PAINEL_EMAIL / PAINEL_SENHA (variáveis de ambiente).
2. Vai em Histórico, filtra "Hoje".
3. Soma pedidos totais, cancelados, GMV bruto e GMV válido (excluindo cancelados).
4. Atualiza o dataStore embutido em index.html (e historico_vendas.json, se presente).
5. Publica no Netlify via CLI (netlify deploy --prod), usando NETLIFY_AUTH_TOKEN / NETLIFY_SITE_ID.

Seletores confirmados manualmente em 17/07/2026 contra o DOM real (via navegador logado):
  - login: <input placeholder="Usuário">, <input placeholder="Senha">, <button>LOGIN</button>
  - histórico: botão de datas mostra o texto "JULHO 17, 2026 - JULHO 17, 2026" (sem a palavra
    "data" nele!) — selecionado por regex de 4 dígitos (ano). Dropdown tem um link "Hoje" que
    JÁ APLICA o filtro sozinho (não existe botão "Aplicar" separado pra presets).
  - texto de contagem: "Exibindo 1 a 10 de 41 resultados." (aparece embaixo da tabela, à
    esquerda, não perto da paginação numerada).
  - "resultados por página": existem DOIS <select> na página (o de resultados por página E o
    de estado/UF no rodapé) — identificar pelo conteúdo das opções (10/25/50/100), não por
    posição, senão pode pegar o select errado.

Requisitos: pip install playwright && playwright install chromium
Variáveis de ambiente necessárias:
  PAINEL_EMAIL, PAINEL_SENHA
  NETLIFY_AUTH_TOKEN, NETLIFY_SITE_ID  (deploy é feito via `netlify` CLI, não por este script)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PAINEL_URL_LOGIN = "https://panel.deliverymuch.com.br/login"
PAINEL_URL_HISTORICO = "https://panel.deliverymuch.com.br/history"

REPO_ROOT = Path(__file__).resolve().parent.parent  # ajuste se a estrutura do repo for diferente
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

BR_TZ = timezone(timedelta(hours=-3))  # Brasília, sem horário de verão atualmente

NAV_TIMEOUT_MS = 45000


def parse_valor_brl(texto: str) -> float:
    """Converte 'R$ 1.234,56' -> 1234.56"""
    limpo = re.sub(r"[^\d,.-]", "", texto)
    limpo = limpo.replace(".", "").replace(",", ".")
    return float(limpo)


def login_painel(page):
    page.goto(PAINEL_URL_LOGIN, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    email = os.environ["PAINEL_EMAIL"]
    senha = os.environ["PAINEL_SENHA"]
    page.get_by_placeholder("Usuário").fill(email)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_role("button", name=re.compile("login", re.I)).click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=NAV_TIMEOUT_MS)


def esperar_carregamento(page):
    """A página usa um overlay global (#global-loading-overlay) pra indicar requisições AJAX
    em andamento. Espera ele aparecer (se for aparecer) e depois sumir, garantindo que a
    tabela já reflete a última ação (filtro de data, troca de página, etc.) antes de seguir.
    Sem isso, duas ações em sequência rápida (ex: clicar 'Hoje' e já trocar o 'resultados por
    página') podem disparar duas requisições que se sobrepõem, e a que responde por último
    'vence' — não necessariamente a mais recente pedida."""
    overlay = page.locator("#global-loading-overlay")
    try:
        overlay.wait_for(state="visible", timeout=2000)
    except PlaywrightTimeoutError:
        pass  # requisição pode ter sido rápida demais pra pegar o overlay aparecendo
    overlay.wait_for(state="hidden", timeout=NAV_TIMEOUT_MS)


def selecionar_100_por_pagina(page):
    """Acha, entre os <select> da página, o que tem opções 10/25/50/100 (resultados por
    página) — não confiar em posição, porque tem outros <select> na página (cidade, empresa,
    estado/UF)."""
    selects = page.locator("select")
    total = selects.count()
    for i in range(total):
        s = selects.nth(i)
        opcoes = s.locator("option").all_inner_texts()
        opcoes_limpo = [o.strip() for o in opcoes]
        if "100" in opcoes_limpo and "50" in opcoes_limpo and "10" in opcoes_limpo:
            s.select_option("100")
            esperar_carregamento(page)
            return
    print("::warning::Não achei o seletor de 'resultados por página' — seguindo com o padrão (pode paginar).")


def coletar_pedidos_hoje(page) -> dict:
    page.goto(PAINEL_URL_HISTORICO, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    esperar_carregamento(page)

    # Botão de datas mostra algo como "JULHO 17, 2026 - JULHO 17, 2026" — identifica pelo ano (4 dígitos).
    page.get_by_role("button", name=re.compile(r"\d{4}")).click(timeout=NAV_TIMEOUT_MS)
    # "Hoje" já aplica o filtro sozinho, sem precisar de um botão "Aplicar" separado.
    page.get_by_text("Hoje", exact=True).click(timeout=NAV_TIMEOUT_MS)
    # Espera o filtro "Hoje" terminar de carregar ANTES de mexer no seletor de página —
    # trocar os dois rápido demais causa corrida entre as duas requisições AJAX (foi a causa
    # real de um bug em que o total voltava errado, tipo de um período de vários dias).
    esperar_carregamento(page)

    selecionar_100_por_pagina(page)

    # Confirma o texto "Exibindo 1 a X de Y resultados." pra pegar o total.
    resumo_locator = page.get_by_text(re.compile(r"Exibindo \d+ a \d+ de \d+ resultados"))
    resumo_locator.wait_for(state="visible", timeout=NAV_TIMEOUT_MS)
    resumo = resumo_locator.inner_text()
    total_pedidos = int(re.search(r"de (\d+) resultados", resumo).group(1))

    rows = page.locator("table tbody tr")
    count = rows.count()
    linhas = []
    for i in range(count):
        row = rows.nth(i)
        valor_texto = row.locator("td", has_text="R$").first.inner_text()
        status_texto = row.inner_text()
        linhas.append({"valor": parse_valor_brl(valor_texto), "cancelado": "Cancelado" in status_texto})

    cancelados = sum(1 for l in linhas if l["cancelado"])
    gmv_total = round(sum(l["valor"] for l in linhas), 2)
    gmv_valido = round(sum(l["valor"] for l in linhas if not l["cancelado"]), 2)
    pct_cancelados = round(cancelados / total_pedidos * 100, 1) if total_pedidos else 0.0

    if count < total_pedidos:
        print(f"::warning::Só {count} de {total_pedidos} pedidos carregados na página (limite de 100). "
              f"Números podem estar levemente subestimados em dias muito cheios.")

    agora = datetime.now(BR_TZ)
    return {
        "data": agora.strftime("%Y-%m-%d"),
        "checado_em": agora.strftime("%H:%M"),
        "fonte": "Painel > Histórico, filtro Hoje",
        "pedidos_totais": total_pedidos,
        "cancelados": cancelados,
        "pct_cancelados": pct_cancelados,
        "gmv_total": gmv_total,
        "gmv_valido": gmv_valido,
    }


def atualizar_arquivos(dados_pedidos: dict):
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        novo_bloco = (
            '"pedidos_ao_vivo_hoje": {\n'
            f'    "data": "{dados_pedidos["data"]}",\n'
            f'    "checado_em": "{dados_pedidos["checado_em"]}",\n'
            f'    "fonte": "{dados_pedidos["fonte"]}",\n'
            f'    "pedidos_totais": {dados_pedidos["pedidos_totais"]},\n'
            f'    "cancelados": {dados_pedidos["cancelados"]},\n'
            f'    "pct_cancelados": {dados_pedidos["pct_cancelados"]},\n'
            f'    "gmv_total": {dados_pedidos["gmv_total"]},\n'
            f'    "gmv_valido": {dados_pedidos["gmv_valido"]}\n'
            '  }'
        )
        texto_novo = re.sub(
            r'"pedidos_ao_vivo_hoje":\s*\{[^}]*\}',
            novo_bloco,
            texto,
            count=1,
            flags=re.DOTALL,
        )
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Atualizado: {path}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            login_painel(page)
            dados = coletar_pedidos_hoje(page)
            print("Coletado:", json.dumps(dados, ensure_ascii=False, indent=2))
            atualizar_arquivos(dados)

            if dados["pct_cancelados"] > 30:
                print(f"::warning::Cancelamento alto hoje: {dados['pct_cancelados']}%")
        except PlaywrightTimeoutError as e:
            print(f"::error::Timeout esperando elemento — provavelmente um seletor mudou: {e}")
            page.screenshot(path="erro_debug.png")
            sys.exit(1)
        except RuntimeError as e:
            print(f"::error::{e}")
            page.screenshot(path="erro_login.png")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
