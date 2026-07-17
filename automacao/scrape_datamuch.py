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
    # Espera algo do conteúdo real do relatório aparecer (não só o iframe existir).
    frame.get_by_text(re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")).first.wait_for(
        state="visible", timeout=NAV_TIMEOUT_MS
    )
    return frame


def ler_ultima_atualizacao(frame) -> datetime:
    locator = frame.get_by_text(re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")).first
    texto = locator.inner_text().strip()
    return datetime.strptime(texto, "%d/%m/%Y %H:%M:%S")


def numero_por_indice(frame, rotulo: str, indice: int, tipo: str = "valor") -> float:
    """Acha a N-ésima ocorrência (0-indexed, ordem visual esquerda->direita / topo->baixo)
    de um rótulo de texto e extrai o número no bloco pai dele. Rótulos como 'Realizado'
    ou '% MoM' se repetem em vários cards, por isso o índice posicional."""
    loc = frame.get_by_text(rotulo, exact=True).nth(indice)
    loc.wait_for(state="visible", timeout=NAV_TIMEOUT_MS)
    bloco = loc.locator("..").inner_text()
    if tipo == "valor":
        m = re.search(r"-?R\$\s?[\d.,]+", bloco)
    else:
        m = re.search(r"-?[\d.,]+\s?%", bloco)
    if not m:
        raise RuntimeError(f"Não achei número perto do rótulo '{rotulo}' (índice {indice}): {bloco!r}")
    texto = m.group(0)
    return parse_pct(texto) if tipo == "pct" else parse_valor_brl(texto)


def clicar_toggle(frame, rotulo: str):
    frame.get_by_role("button", name=re.compile(rotulo, re.I)).click(timeout=NAV_TIMEOUT_MS)
    frame.get_by_text(re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")).first.wait_for(
        state="visible", timeout=NAV_TIMEOUT_MS
    )


def coletar_contexto(frame) -> dict:
    """Coleta os campos de contexto_mensal, primeiro na visão GMV, depois trocando pra
    visão Pedidos."""
    # --- Visão GMV (já é a padrão ao abrir o relatório) ---
    gmv_realizado_mes = numero_por_indice(frame, "Realizado", 0, "valor")
    gmv_mom_pct = numero_por_indice(frame, "% MoM", 0, "pct")
    gmv_yoy_pct = numero_por_indice(frame, "% YoY", 0, "pct")
    media_gmv_dia = numero_por_indice(frame, "Realizado", 1, "valor")
    # "GMV Projetado" e "Meta" não têm rótulo "Realizado" — pega pelo cabeçalho do card.
    gmv_projetado_mes = numero_por_indice(frame, "GMV Projetado", 0, "valor")
    meta_mes = numero_por_indice(frame, "Meta", 0, "valor")
    meta_ate_ontem = numero_por_indice(frame, "Meta até ontem", 0, "valor")
    pct_realizado_ate_ontem = numero_por_indice(frame, "% Realizado até ontem", 0, "pct")
    gmv_acumulado_ano = numero_por_indice(frame, "Acumulado", 0, "valor")
    gmv_ate_ontem_ano = numero_por_indice(frame, "GMV ano anterior", 0, "valor")
    gmv_yoy_ano_pct = numero_por_indice(frame, "% YoY", 2, "pct")

    # --- Troca pra visão Pedidos ---
    clicar_toggle(frame, "Pedidos")
    pedidos_realizado_mes = int(numero_por_indice(frame, "Realizado", 0, "valor"))
    media_pedidos_dia = int(numero_por_indice(frame, "Realizado", 1, "valor"))
    pedidos_projetado_mes = int(numero_por_indice(frame, "GMV Projetado", 0, "valor"))
    meta_pedidos_mes = int(numero_por_indice(frame, "Meta", 0, "valor"))
    meta_pedidos_ate_ontem = int(numero_por_indice(frame, "Meta até ontem", 0, "valor"))
    pct_pedidos_realizado_ate_ontem = numero_por_indice(frame, "% Realizado até ontem", 0, "pct")
    pedidos_acumulado_ano = int(numero_por_indice(frame, "Acumulado", 0, "valor"))
    pedidos_yoy_ano_pct = numero_por_indice(frame, "% YoY", 2, "pct")
    # Volta pra visão GMV (deixa a UI como estava, por precaução).
    clicar_toggle(frame, "GMV")

    return {
        "mes_referencia": datetime.now(BR_TZ).strftime("%Y-%m"),
        "atualizado_em": datetime.now(BR_TZ).strftime("%Y-%m-%dT%H:%M:%S"),
        "gmv_realizado_mes": round(gmv_realizado_mes, 2),
        "gmv_mom_pct": gmv_mom_pct,
        "gmv_yoy_pct": gmv_yoy_pct,
        "media_gmv_dia": round(media_gmv_dia, 2),
        "gmv_projetado_mes": round(gmv_projetado_mes),
        "meta_mes": round(meta_mes),
        "meta_ate_ontem": round(meta_ate_ontem),
        "pct_realizado_ate_ontem": pct_realizado_ate_ontem,
        "gmv_acumulado_ano": round(gmv_acumulado_ano, 2),
        "gmv_ate_ontem_ano": round(gmv_ate_ontem_ano, 2),
        "gmv_yoy_ano_pct": gmv_yoy_ano_pct,
        "pedidos_realizado_mes": pedidos_realizado_mes,
        "media_pedidos_dia": media_pedidos_dia,
        "pedidos_projetado_mes": pedidos_projetado_mes,
        "meta_pedidos_mes": meta_pedidos_mes,
        "meta_pedidos_ate_ontem": meta_pedidos_ate_ontem,
        "pct_pedidos_realizado_ate_ontem": pct_pedidos_realizado_ate_ontem,
        "pedidos_acumulado_ano": pedidos_acumulado_ano,
        "pedidos_yoy_ano_pct": pedidos_yoy_ano_pct,
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


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
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
                # Mesmo sem mudança de dados, atualiza "verificado_em" pra registrar que checamos
                # (só no JSON local — não vale a pena commitar/deployar só por isso, o
                # workflow não roda os passos de deploy/commit quando mudou=false).
                status = historico_atual.setdefault("data_much_status", {})
                status["verificado_em"] = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
                escrever_output("mudou", "false")
                return

            print(f"Novidade encontrada no Data Much! Última atualização lá: {data_datamuch}")
            novo_contexto = coletar_contexto(frame)
            gmv_diario_novo = atualizar_gmv_diario(historico_atual.get("gmv_diario_mes", []), novo_contexto)
            atualizar_arquivos(novo_contexto, gmv_diario_novo, data_datamuch, novo_dia_detectado=True)
            escrever_output("mudou", "true")

        except PlaywrightTimeoutError as e:
            print(f"::error::Timeout esperando elemento — provavelmente um seletor mudou: {e}")
            page.screenshot(path="erro_debug_datamuch.png")
            escrever_output("mudou", "false")
            sys.exit(1)
        except RuntimeError as e:
            print(f"::error::{e}")
            page.screenshot(path="erro_datamuch.png")
            escrever_output("mudou", "false")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
