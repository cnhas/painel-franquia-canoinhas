"""
Scraper de pedidos ao vivo — Painel Delivery Much (Canoinhas/Três Barras)

O que faz:
1. Loga em https://panel.deliverymuch.com.br com PAINEL_EMAIL / PAINEL_SENHA (variáveis de ambiente).
2. Vai em Histórico, filtra "Hoje".
3. Soma pedidos totais, cancelados, GMV bruto e GMV válido (excluindo cancelados).
4. Atualiza o dataStore embutido em index.html (e historico_vendas.json, se presente).
5. Publica no Netlify via CLI (netlify deploy --prod), usando NETLIFY_AUTH_TOKEN / NETLIFY_SITE_ID.

Seletores de login confirmados manualmente em 17/07/2026 (tela real):
  - campo usuário: <input type="text" placeholder="Usuário">  (sem <label>)
  - campo senha:   <input type="password" placeholder="Senha">
  - botão:         <button type="submit">LOGIN</button>

Os seletores da tela de Histórico (filtro de data, tabela de resultados) ainda são
melhor-esforço — se o job falhar depois do login, é ali. Rode manualmente (workflow_dispatch)
e ajuste conforme o erro indicar.

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


def parse_valor_brl(texto: str) -> float:
    """Converte 'R$ 1.234,56' -> 1234.56"""
    limpo = re.sub(r"[^\d,.-]", "", texto)
    limpo = limpo.replace(".", "").replace(",", ".")
    return float(limpo)


def login_painel(page):
    page.goto(PAINEL_URL_LOGIN, wait_until="networkidle")
    email = os.environ["PAINEL_EMAIL"]
    senha = os.environ["PAINEL_SENHA"]
    page.get_by_placeholder("Usuário").fill(email)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_role("button", name=re.compile("login", re.I)).click()
    page.wait_for_load_state("networkidle")
    # Confere que saiu da tela de login (se ainda estiver em /login, as credenciais falharam).
    if "/login" in page.url:
        raise RuntimeError("Login falhou — ainda na tela de login após submeter. Confira PAINEL_EMAIL/PAINEL_SENHA.")


def coletar_pedidos_hoje(page) -> dict:
    page.goto(PAINEL_URL_HISTORICO, wait_until="networkidle")

    # TODO: confirmar seletor real do botão/campo de filtro de datas (ainda não verificado
    # contra o DOM real — só contra o texto visível da tela).
    page.get_by_role("button", name=re.compile("data", re.I)).first.click()
    page.get_by_text("Hoje", exact=True).click()
    page.get_by_role("button", name=re.compile("aplicar|apply", re.I)).click()
    page.wait_for_load_state("networkidle")

    # Confirma o texto "Exibindo 1 a X de Y resultados" pra pegar o total.
    resumo = page.get_by_text(re.compile(r"Exibindo \d+ a \d+ de \d+ resultados")).inner_text()
    total_pedidos = int(re.search(r"de (\d+) resultados", resumo).group(1))

    linhas = []
    pagina = 1
    while True:
        # TODO: confirmar seletor real das linhas da tabela.
        rows = page.locator("table tbody tr")
        count = rows.count()
        for i in range(count):
            row = rows.nth(i)
            valor_texto = row.locator("td", has_text="R$").first.inner_text()
            status_texto = row.inner_text()
            linhas.append({"valor": parse_valor_brl(valor_texto), "cancelado": "Cancelado" in status_texto})

        proxima = page.get_by_role("button", name=re.compile("próxima|next", re.I))
        if proxima.is_enabled():
            proxima.click()
            page.wait_for_load_state("networkidle")
            pagina += 1
        else:
            break

    cancelados = sum(1 for l in linhas if l["cancelado"])
    gmv_total = round(sum(l["valor"] for l in linhas), 2)
    gmv_valido = round(sum(l["valor"] for l in linhas if not l["cancelado"]), 2)
    pct_cancelados = round(cancelados / total_pedidos * 100, 1) if total_pedidos else 0.0

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
        # Substitui o bloco "pedidos_ao_vivo_hoje": { ... } por regex controlada.
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
