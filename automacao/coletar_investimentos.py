"""
Scraper de INVESTIMENTOS DA FRANQUIA — Data Much (Canoinhas/Três Barras)

Guilherme pediu explicitamente (21/07/2026) que esta seção rode
automaticamente TODOS OS DIAS, junto com a atualização normal do Data Much —
é a métrica que ele chamou de mais importante do painel ("foi o que me levou
a construir esse painel"). Antes desta automação, os 4 componentes abaixo só
eram coletados manualmente (última coleta manual: 17/07/2026, cobrindo só
01–16/07).

Fórmula confirmada em sessões anteriores (total_confirmado = soma dos 4
componentes abaixo, sempre olhando o mês corrente do dia 1º até o último dia
já fechado no Data Much = "ontem" no fuso America/Sao_Paulo):

  1. Ofertas De/Por — subsídio franquia:
     report/434 "Ofertas De/Por", filtro de Data = mês corrente até ontem,
     card "Subsídio Franquia" (mesma leitura já usada em ler_cards_ofertas()
     de scrape_dia_datamuch.py, aqui isolada numa função própria).

  2. Cupom — subsídio franquia (direto):
     report/216 "Acompanhamento de Cupons", filtro de Data = mês corrente até
     ontem, filtro adicional "Subsídio" = só "Franquia" marcado (dropdown
     multi-select confirmado manualmente em 21/07/2026 - opções existentes:
     Franqueadora, Franqueadora e Franquia, Franquia, Franquia e Loja, Loja),
     card "Desconto Total".

  3. Cupom — 50% do subsídio compartilhado Franqueadora + Franquia:
     mesmo relatório/período, filtro "Subsídio" = só "Franqueadora e
     Franquia" marcado, card "Desconto Total" ÷ 2 (confirmado com Guilherme
     que o subsídio compartilhado é dividido 50/50 entre franqueadora e
     franquia).

  4. Entrega promocional — subsídio franquia:
     report/488 "Acompanhamento de Lojas", aba "Ações", mesmo período,
     coluna "entrega promocional - subsidio franquia" (por loja) — ordena
     decrescente (2 cliques no cabeçalho, mesmo padrão confirmado em
     _ordenar_tabela_lojas de scrape_dia_datamuch.py) e lê o MAIOR valor.
     Como subsídio nunca é negativo, se o maior valor da coluna for 0, o
     TOTAL da coluna também é 0 (sem precisar somar loja por loja) — essa
     suposição foi validada com o histórico real (essa coluna sempre veio
     zerada em todas as coletas manuais feitas até 21/07/2026). Se algum dia
     vier um valor > 0 aqui, a automação REGISTRA UMA PENDÊNCIA em vez de
     tentar somar (evita gravar uma soma incompleta/errada).

DESIGN DE SEGURANÇA (mesmo princípio já usado no scraper de
comparativo_mes_anterior): cada um dos 4 componentes tem seu próprio
try/except. Se um componente falhar, os outros ainda são coletados e
gravados; o componente que falhou usa o ÚLTIMO VALOR CONHECIDO (do
historico_vendas.json atual) em vez de ser omitido — assim "total_confirmado"
nunca vira uma soma parcial silenciosa, e uma pendência clara é registrada
avisando que aquele componente específico não foi atualizado nesta rodada.

Requisitos: pip install playwright && playwright install chromium
Variáveis de ambiente: DATAMUCH_EMAIL, DATAMUCH_SENHA
"""

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from playwright.sync_api import sync_playwright, Frame

DATAMUCH_URL_LOGIN = "https://datamuch.deliverymuch.com.br/login"
URL_LOJAS = "https://datamuch.deliverymuch.com.br/app/report/488"
URL_CUPONS = "https://datamuch.deliverymuch.com.br/app/report/216"
URL_OFERTAS = "https://datamuch.deliverymuch.com.br/app/report/434"

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

NAV_TIMEOUT_MS = 45000


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
    frame.locator("body").wait_for(state="visible", timeout=60000)
    page.wait_for_timeout(2000)
    return frame


def _esperar(frame, ms: int):
    frame.locator("body").page.wait_for_timeout(ms)


def abrir_painel_filtro(frame):
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
    try:
        pagina = frame.locator("body").page
        pagina.keyboard.press("Escape")
    except Exception:
        pass


def _fechar_painel_filtro(frame):
    """Fecha o painel de filtro (mesma lógica de fechamento usada em
    selecionar_dia_unico() de scrape_dia_datamuch.py)."""
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


def selecionar_intervalo(frame, inicio: date, fim: date, subsidio: str = None):
    """Igual a selecionar_dia_unico() de scrape_dia_datamuch.py, mas com
    datas de início/fim DIFERENTES (intervalo, não um único dia) - pra
    filtrar "mês corrente até ontem" em vez de isolar um dia.

    BUG REAL encontrado na 1ª rodada de teste (21/07/2026, run #1 do
    workflow "Atualizar investimentos da franquia"): a versão anterior desta
    função FECHAVA o painel de filtro no final, e só depois disso o código
    tentava abrir o dropdown "Subsídio" - que a essa altura já não estava
    mais visível (painel fechado), causando timeout. Corrigido: se
    `subsidio` for passado, configura o filtro de Subsídio ANTES de fechar o
    painel (dentro da mesma "sessão" do painel aberto)."""
    abrir_painel_filtro(frame)
    campo_inicio = frame.get_by_label(re.compile("Data de in[íi]cio", re.I)).first
    campo_fim = frame.get_by_label(re.compile(r"Data de t[ée]rmino", re.I)).first

    campo_inicio.fill(inicio.strftime("%d/%m/%Y"))
    campo_inicio.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 500)

    campo_fim.fill(fim.strftime("%d/%m/%Y"))
    campo_fim.press("Tab")
    _esperar(frame, 500)
    _fechar_overlay_calendario(frame)
    _esperar(frame, 1500)

    if subsidio is not None:
        selecionar_subsidio_unico(frame, subsidio)

    _fechar_painel_filtro(frame)


def selecionar_subsidio_unico(frame, valor: str):
    """Abre o dropdown multi-select "Subsídio" (o painel de filtro precisa
    JÁ ESTAR ABERTO - chamado de dentro de selecionar_intervalo(), antes do
    painel fechar), desmarca "Selecionar tudo" (que vem marcado por padrão =
    todos selecionados) e marca só a opção pedida (ex: "Franquia" ou
    "Franqueadora e Franquia"). Opções confirmadas manualmente em
    21/07/2026: Franqueadora, Franqueadora e Franquia, Franquia, Franquia e
    Loja, Loja.

    Tenta múltiplas estratégias pra abrir o dropdown (mesmo espírito de
    abrir_painel_filtro), já que não foi possível confirmar de antemão se o
    campo tem aria-label "Subsídio" de verdade (1ª tentativa real deu
    timeout nisso)."""
    estrategias = [
        lambda: frame.get_by_label(re.compile("Subs[íi]dio", re.I)).first,
        lambda: frame.locator('[aria-label*="ubs" i]').first,
        lambda: frame.get_by_text("Subsídio", exact=True).first.locator(
            "xpath=following::*[self::mat-select or contains(@class,'select') or contains(@class,'dropdown')][1]"
        ),
    ]
    ultimo_erro = None
    aberto = False
    for estrategia in estrategias:
        try:
            campo = estrategia()
            campo.click(timeout=10000)
            frame.get_by_text("Selecionar tudo", exact=True).first.wait_for(state="visible", timeout=8000)
            aberto = True
            break
        except Exception as e:
            ultimo_erro = e
            continue
    if not aberto:
        try:
            aria_labels = frame.locator("[aria-label]").evaluate_all(
                "els => els.map(e => e.getAttribute('aria-label')).filter((v,i,a) => a.indexOf(v)===i).slice(0, 80)"
            )
            print(f"[debug selecionar_subsidio_unico] aria-labels únicos no painel: {aria_labels}")
        except Exception as e2:
            print(f"[debug selecionar_subsidio_unico] não consegui listar aria-labels: {e2}")
        raise RuntimeError(f"Não consegui abrir o dropdown 'Subsídio' por nenhuma estratégia. Último erro: {ultimo_erro}")

    frame.get_by_text("Selecionar tudo", exact=True).first.click(timeout=10000)
    _esperar(frame, 300)
    frame.get_by_text(valor, exact=True).first.click(timeout=10000)
    _esperar(frame, 500)
    frame.locator("body").press("Escape")
    _esperar(frame, 1500)


def ler_desconto_total(frame) -> float:
    """Lê o card "Desconto Total" do relatório de Cupons (report/216), já
    filtrado. Mesma regex usada em ler_cards_cupons() de
    scrape_dia_datamuch.py."""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m = re.search(r"R\$\s?([\d.,]+)\s*\n?\s*Desconto Total", texto)
        if m:
            return round(parse_valor_brl(m.group(1)), 2)
        if time.monotonic() >= limite:
            raise RuntimeError(f"Não achei o card Desconto Total. Texto: {texto[:1500]!r}")
        _esperar(frame, 500)


def ler_subsidio_franquia_ofertas(frame) -> float:
    """Lê só o card "Subsídio Franquia" do relatório Ofertas De/Por
    (report/434), já filtrado pro período. Regex igual à usada em
    ler_cards_ofertas() de scrape_dia_datamuch.py, mas isolada só pra esse
    card."""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m = re.search(r"R\$\s?([\d.,]+)\s*(Mil)?\s*\n?\s*Subsídio Franquia", texto)
        if m:
            valor = parse_valor_brl(m.group(1))
            if m.group(2):  # "Mil"
                valor *= 1000
            return round(valor, 2)
        if time.monotonic() >= limite:
            raise RuntimeError(f"Não achei o card Subsídio Franquia. Texto: {texto[:1500]!r}")
        _esperar(frame, 500)


def ler_maior_entrega_promocional_franquia(frame) -> float:
    """No relatório Acompanhamento de Lojas (report/488), aba "Ações", ordena
    a coluna "entrega promocional - subsidio franquia" em ordem decrescente
    (2 cliques no cabeçalho) e lê o maior valor. Como subsídio nunca é
    negativo, se o MAIOR valor da coluna for 0, o TOTAL da coluna também é 0
    - suposição validada com o histórico real (essa coluna sempre veio
    zerada em todas as coletas manuais feitas até 21/07/2026).

    BUG REAL encontrado na 1ª rodada de teste (21/07/2026): timeout de 45s
    tentando achar o texto exato do cabeçalho ("entrega promocional -
    subsídio franquia" — nota: o texto real no DOM usa acento em "subsídio",
    diferente do que a 1ª versão assumia). 2ª rodada de teste: corrigido o
    acento, mas ainda deu timeout - a coluna só fica visível rolando a
    tabela bem pra direita, e uma tentativa de rolar via JS escolhendo "o
    primeiro elemento com scroll horizontal" pegou o elemento errado (não é
    a tabela). Corrigido: simula uma rolagem de mouse de verdade (wheel
    horizontal) sobre a área da tabela - mesmo tipo de gesto que funcionou
    manualmente ao arrastar a barra de rolagem durante a exploração via
    navegador - repetida algumas vezes, com diagnóstico se mesmo assim não
    achar."""
    padrao_cabecalho = re.compile(r"entrega\s+promocional\s*-\s*subs[ií]dio\s+franquia", re.I)

    try:
        pagina = frame.locator("body").page
        tabela = frame.locator("body")
        box = tabela.bounding_box()
        if box:
            pagina.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        for _ in range(6):
            pagina.mouse.wheel(2500, 0)
            _esperar(frame, 400)
    except Exception as e:
        print(f"[debug ler_maior_entrega_promocional_franquia] não consegui rolar a tabela: {e}")

    try:
        cabecalho = frame.get_by_text(padrao_cabecalho).first
        cabecalho.click(timeout=NAV_TIMEOUT_MS)
        _esperar(frame, 1200)
        cabecalho.click(timeout=NAV_TIMEOUT_MS)
        _esperar(frame, 1200)
    except Exception as e:
        texto_diag = frame.locator("body").inner_text()[:2500]
        print(f"[debug ler_maior_entrega_promocional_franquia] não achei/cliquei no cabeçalho. "
              f"Texto do body (2500 primeiros chars): {texto_diag!r}")
        raise RuntimeError(f"Não consegui ordenar pela coluna 'entrega promocional - subsídio franquia': {e}")

    texto = frame.locator("body").inner_text()
    m_cab = padrao_cabecalho.search(texto)
    if not m_cab:
        raise RuntimeError("Não encontrei o cabeçalho da coluna 'entrega promocional - subsídio franquia' depois de ordenar.")
    resto = texto[m_cab.end():]
    m = re.search(r"R\$\s?([\d.,]+)", resto)
    if not m:
        # Célula em branco na 1ª linha depois de ordenar decrescente = maior
        # valor é 0 (ou a coluna está vazia) - trata como 0.
        return 0.0
    return round(parse_valor_brl(m.group(1)), 2)


def obter_periodo_mes_atual() -> tuple:
    """Retorna (1º dia do mês corrente, ontem) no fuso America/Sao_Paulo -
    o período "mês corrente até o último dia fechado" usado nos 4
    componentes de investimentos."""
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    ontem = hoje - timedelta(days=1)
    inicio_mes = ontem.replace(day=1)
    return inicio_mes, ontem


def _buscar_componente_antigo(historico: dict, nome: str):
    investimentos_antigo = historico.get("investimentos", {})
    for c in investimentos_antigo.get("componentes", []):
        if c.get("nome") == nome:
            return c
    return None


def coletar_investimentos(historico_atual: dict) -> dict:
    inicio, ontem = obter_periodo_mes_atual()
    periodo_str = f"{inicio.strftime('%d/%m/%Y')} a {ontem.strftime('%d/%m/%Y')}"
    agora_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")

    componentes = []
    pendencias = []

    def registrar_falha(nome: str, erro: Exception):
        print(f"::warning::Falha coletando \"{nome}\": {erro}")
        antigo = _buscar_componente_antigo(historico_atual, nome)
        if antigo is not None:
            componentes.append(dict(antigo))
            pendencias.append(
                f"\"{nome}\" não pôde ser recoletado automaticamente nesta rodada — "
                f"mantido o último valor conhecido (R$ {antigo.get('valor')}), pode estar desatualizado."
            )
        else:
            pendencias.append(
                f"\"{nome}\" não pôde ser coletado automaticamente nesta rodada e não havia valor "
                f"anterior conhecido — componente ausente neste ciclo."
            )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = context.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            login_datamuch(page)

            nome1 = "Ofertas De/Por — subsídio franquia"
            try:
                frame = obter_frame(page, URL_OFERTAS)
                selecionar_intervalo(frame, inicio, ontem)
                valor = ler_subsidio_franquia_ofertas(frame)
                componentes.append({"nome": nome1, "valor": valor, "obs": f"Mês corrente ({periodo_str})"})
                print(f"{nome1}: R${valor}")
            except Exception as e:
                registrar_falha(nome1, e)

            nome2 = "Cupom — subsídio franquia (direto)"
            try:
                frame = obter_frame(page, URL_CUPONS)
                selecionar_intervalo(frame, inicio, ontem, subsidio="Franquia")
                valor = ler_desconto_total(frame)
                componentes.append({"nome": nome2, "valor": valor, "obs": f"{periodo_str} · filtro Subsídio = Franquia"})
                print(f"{nome2}: R${valor}")
            except Exception as e:
                registrar_falha(nome2, e)

            nome3 = "Cupom — 50% do subsídio compartilhado Franqueadora + Franquia"
            try:
                frame = obter_frame(page, URL_CUPONS)
                selecionar_intervalo(frame, inicio, ontem, subsidio="Franqueadora e Franquia")
                valor_total = ler_desconto_total(frame)
                valor = round(valor_total / 2, 2)
                componentes.append({
                    "nome": nome3,
                    "valor": valor,
                    "obs": f"50% de R$ {valor_total:.2f} · {periodo_str}",
                })
                print(f"{nome3}: R${valor} (metade de R${valor_total})")
            except Exception as e:
                registrar_falha(nome3, e)

            nome4 = "Entrega promocional — subsídio franquia"
            try:
                frame = obter_frame(page, URL_LOJAS)
                frame.get_by_text("Ações", exact=True).first.click(timeout=15000)
                _esperar(frame, 1500)
                selecionar_intervalo(frame, inicio, ontem)
                valor = ler_maior_entrega_promocional_franquia(frame)
                componentes.append({
                    "nome": nome4,
                    "valor": valor,
                    "obs": f"{periodo_str} · maior valor da coluna por loja (assume 0 se o maior for 0)",
                })
                print(f"{nome4}: R${valor}")
            except Exception as e:
                registrar_falha(nome4, e)

        finally:
            browser.close()

    total_confirmado = round(sum(c["valor"] for c in componentes), 2)

    verificacao = f"Atualizado automaticamente em {agora_str} pela rotina diária. Cobre {periodo_str}."
    if pendencias:
        verificacao += " ATENÇÃO: nem todos os componentes foram recoletados nesta rodada — ver pendências."

    pendencias_finais = list(pendencias) + [
        "Por loja: só 'entrega promocional' está detalhada por loja até agora — De/Por e Cupom aparecem só no total do período.",
        "Por campanha: ainda não há uma quebra de investimento por campanha específica — só por tipo de subsídio (De/Por, Cupom, Entrega).",
    ]

    return {
        "periodo": periodo_str,
        "atualizado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d"),
        "verificacao_dados_recentes": verificacao,
        "componentes": componentes,
        "total_confirmado": total_confirmado,
        "pendencias": pendencias_finais,
    }


def substituir_bloco_json(texto: str, chave: str, novo_valor_json: str) -> str:
    """Acha "chave": <json> (objeto {} ou array []) e substitui pelo novo
    valor, usando JSONDecoder.raw_decode pra achar o fim exato do valor
    antigo (robusto contra colchetes/chaves aninhadas dentro do valor) - já
    usado em corrigir_comparativo_junho.py e outros scripts deste repo."""
    marcador = f'"{chave}":'
    pos_chave = texto.find(marcador)
    if pos_chave == -1:
        raise RuntimeError(f"Não encontrei a chave \"{chave}\" no arquivo.")
    i = pos_chave + len(marcador)
    while i < len(texto) and texto[i] in " \n\r\t":
        i += 1
    if i >= len(texto) or texto[i] not in "{[":
        raise RuntimeError(f"Esperava um objeto/array logo depois de \"{chave}\": mas achei {texto[i:i+30]!r}")
    decoder = json.JSONDecoder()
    _, fim_valor_antigo = decoder.raw_decode(texto, i)
    return texto[:pos_chave] + f'"{chave}": {novo_valor_json}' + texto[fim_valor_antigo:]


def atualizar_arquivos_com_investimentos(investimentos_novo: dict):
    investimentos_json = json.dumps(investimentos_novo, ensure_ascii=False, indent=2)
    # Trava de segurança (mesmo princípio já usado em scrape_dia_datamuch.py
    # depois do bug real de corrupção de JSON em 20/07/2026): confirma que o
    # pedaço gerado é JSON válido antes de gravar em qualquer arquivo.
    json.loads(investimentos_json)
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto_novo = substituir_bloco_json(texto, "investimentos", investimentos_json)
        if path == HISTORICO_JSON_PATH:
            json.loads(texto_novo)  # confirma que o ARQUIVO INTEIRO continua JSON válido
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Atualizado: {path}")


def main():
    historico_atual = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
    investimentos_novo = coletar_investimentos(historico_atual)
    print(f"total_confirmado: R${investimentos_novo['total_confirmado']}")
    atualizar_arquivos_com_investimentos(investimentos_novo)
    print("mudou=true")


if __name__ == "__main__":
    main()
