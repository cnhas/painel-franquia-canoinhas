"""
Script de correcao pontual (rodar 1x): conserta um bug real e serio encontrado em
22/09/2026 ao checar "como esta o funcionamento" do painel - gmv_diario_mes estava
CONGELADO desde 2026-08-01 (mais de 7 semanas sem nenhum dia novo), porque
atualizar_gmv_diario() (em automacao/scrape_datamuch.py) calculava o dia novo por
DIFERENCA entre o total "mes atual" (que reinicia do zero a cada mes) e a soma de
TODOS os dias ja registrados em gmv_diario_mes (que acumula meses anteriores
inteiros, sem nunca "zerar"). Na virada de julho->agosto isso fez o delta ficar
permanentemente negativo (soma acumulada de julho inteiro > total do mes de agosto
que estava so comecando), e a funcao simplesmente parava de adicionar dias pra
sempre (`if delta <= 0: return gmv_diario_atual`), sem nenhum erro/aviso - o
workflow continuava "rodando com sucesso" todo dia, so nunca mais achava novidade
de verdade.

Efeito em cascata: como scrape_dia_datamuch.py busca o gmv_dia OFICIAL de cada dia
em gmv_diario_mes (_buscar_gmv_meta), TODO dia desde 2026-08-02 ficou sem gmv_dia/
meta_dia no painel "ver o dia", e o comparativo com o mes anterior (que so fecha
quando o gmv_dia oficial esta disponivel) ficou permanentemente pendente tambem -
exatamente o problema que motivou essa investigacao.

Correcao: substitui a logica de delta por uma versao que NUNCA mais trava -
descobre exatamente quais dias estao faltando entre o ultimo dia registrado e
"ontem" (fuso America/Sao_Paulo), e busca cada um INDIVIDUALMENTE, direto do
report/208 com o filtro de Data isolado num unico dia (mesma tecnica ja usada e
validada - bate centavo a centavo - pro comparativo_mes_anterior em
scrape_dia_datamuch.py). Isso e' auto-recuperavel: mesmo que fique alguns dias sem
rodar por qualquer motivo, a proxima execucao preenche todos os dias que faltarem
de uma vez, sem depender de nenhuma soma acumulada que possa ficar inconsistente
numa virada de mes.

Depois de rodar este script (que so mexe no CODIGO), ainda e' preciso disparar
manualmente o workflow "Atualizar Data Much" (workflow_dispatch) pra essa logica
nova rodar de verdade e preencher os ~7 semanas de dias que faltam.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "automacao" / "scrape_datamuch.py"


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

    # 1) import de `date` (usado nos type hints das novas funcoes).
    texto = aplicar(
        texto,
        "from datetime import datetime, timedelta, timezone",
        "from datetime import datetime, timedelta, timezone, date",
        "import date",
    )

    # 2) novas funcoes auxiliares (dia unico via filtro de Data), inseridas logo
    #    apos parse_pct() e antes de login_datamuch().
    ANCORA_ANTIGA = '''def parse_pct(texto: str) -> float:
    limpo = texto.replace("%", "").replace(",", ".").strip()
    return float(limpo)

def login_datamuch(page):'''

    FUNCOES_NOVAS = '''def parse_pct(texto: str) -> float:
    limpo = texto.replace("%", "").replace(",", ".").strip()
    return float(limpo)

def _esperar(frame, ms: int):
    """FrameLocator nao tem wait_for_timeout (so Page/Frame tem) - pega a Page
    dona do frame via um Locator qualquer dentro dele e espera por ali (mesmo
    helper ja usado e validado em scrape_dia_datamuch.py)."""
    frame.locator("body").page.wait_for_timeout(ms)

def _fechar_overlay_calendario(frame):
    """Se preencher o campo de data abriu um calendario overlay por cima da
    tela, fecha com Escape. Nao e' erro se nao tiver nada pra fechar (mesmo
    helper ja usado e validado em scrape_dia_datamuch.py)."""
    try:
        pagina = frame.locator("body").page
        pagina.keyboard.press("Escape")
    except Exception:
        pass

def obter_frame_dia_unico(page):
    """Navegacao leve pro report/208 pra ler UM dia isolado via filtro de Data -
    mesmo padrao comprovado em scrape_dia_datamuch.py (obter_frame), mais rapido
    que obter_frame_relatorio() porque nao espera especificamente pelo texto de
    'Ultima Atualizacao' (que nao faz diferenca pra leitura de um dia filtrado)."""
    page.goto(DATAMUCH_URL_RELATORIO, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    frame = page.frame_locator("iframe").first
    frame.locator("body").wait_for(state="visible", timeout=60000)
    page.wait_for_timeout(2000)
    return frame

def selecionar_dia_unico_sem_filtro(frame, dia: date):
    """Preenche os campos de Data do report/208 (ja visiveis direto na tela, sem
    precisar abrir painel de filtro) pra isolar UM unico dia (inicio = fim = dia).
    Mesma tecnica ja usada e validada em scrape_dia_datamuch.py pro
    comparativo_mes_anterior - confirmado bater centavo a centavo com os dados
    oficiais."""
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
    """Le os cards GMV (Realizado) e Meta do report/208 ja filtrado pra um unico
    dia. Retorna (gmv, meta). Mesma funcao ja usada e validada em
    scrape_dia_datamuch.py."""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_gmv = re.search(r"\bGMV\b\s*\n?\s*R\$\s?([\d.,]+)\s*\n?\s*Realizado", texto)
        m_meta = re.search(r"\bMeta\b\s*\n?\s*R\$\s?([\d.,]+)\s*\n?\s*Meta\b", texto)
        if m_gmv and m_meta:
            return round(parse_valor_brl(m_gmv.group(1)), 2), round(parse_valor_brl(m_meta.group(1)), 2)
        if time.monotonic() >= limite:
            raise RuntimeError(f"Nao achei os cards GMV/Meta (dia unico). Texto: {texto[:1500]!r}")
        _esperar(frame, 500)

def login_datamuch(page):'''

    texto = aplicar(texto, ANCORA_ANTIGA, FUNCOES_NOVAS, "funcoes auxiliares de dia unico")

    # 3) substitui atualizar_gmv_diario() (baseada em delta, com o bug de virada
    #    de mes) por preencher_dias_faltantes_gmv_diario() (auto-recuperavel,
    #    busca cada dia faltante individualmente).
    FUNCAO_ANTIGA = '''def atualizar_gmv_diario(gmv_diario_atual: list, novo_contexto: dict) -> list:
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
    return gmv_diario_atual'''

    FUNCAO_NOVA = '''def preencher_dias_faltantes_gmv_diario(page, gmv_diario_atual: list, ultimo_dia_disponivel) -> list:
    """SUBSTITUI a antiga atualizar_gmv_diario() (baseada em delta entre o total
    "mês atual" e a soma dos dias já registrados). BUG REAL encontrado em
    22/09/2026: na virada de mês o total "mês atual" reinicia do zero, mas a
    soma acumulada dos dias registrados continha meses anteriores inteiros —
    fazendo o delta ficar permanentemente negativo e travando gmv_diario_mes pra
    sempre depois da primeira virada de mês (ficou congelado em 2026-08-01 por
    mais de 7 semanas, sem nenhum erro visível — o workflow continuava "rodando
    com sucesso" todo dia).

    Esta versão nunca mais trava: descobre exatamente quais dias estão faltando
    entre o último dia registrado (exclusive) e ultimo_dia_disponivel (o "ontem"
    do fuso de Canoinhas/Três Barras), e busca cada um INDIVIDUALMENTE, direto do
    report/208 com o filtro de Data isolado num único dia — mesma técnica já
    validada (bate centavo a centavo) usada pro comparativo_mes_anterior em
    scrape_dia_datamuch.py. Auto-recuperável: se ficar dias sem rodar por
    qualquer motivo, a próxima execução preenche todos de uma vez, sem depender
    de nenhuma soma acumulada."""
    if not gmv_diario_atual:
        return gmv_diario_atual

    gmv_diario_atual = list(gmv_diario_atual)
    datas_existentes = {d["data"] for d in gmv_diario_atual}
    ultimo_dia_registrado = datetime.strptime(gmv_diario_atual[-1]["data"], "%Y-%m-%d").date()

    dia_cursor = ultimo_dia_registrado + timedelta(days=1)
    while dia_cursor <= ultimo_dia_disponivel:
        data_str = dia_cursor.strftime("%Y-%m-%d")
        if data_str not in datas_existentes:
            print(f"[gmv_diario_mes] buscando dia faltante {data_str} via filtro de dia único...")
            frame = obter_frame_dia_unico(page)
            selecionar_dia_unico_sem_filtro(frame, dia_cursor)
            gmv_dia, meta_dia = ler_gmv_meta_dia_unico(frame)
            gmv_diario_atual.append({"data": data_str, "gmv": gmv_dia, "meta": meta_dia})
            datas_existentes.add(data_str)
            print(f"[gmv_diario_mes] {data_str}: gmv={gmv_dia} meta={meta_dia}")
        dia_cursor += timedelta(days=1)

    gmv_diario_atual.sort(key=lambda d: d["data"])
    return gmv_diario_atual'''

    texto = aplicar(texto, FUNCAO_ANTIGA, FUNCAO_NOVA, "atualizar_gmv_diario -> preencher_dias_faltantes_gmv_diario")

    # 4) ponto de chamada em main(): troca a chamada antiga pela nova (agora
    #    passando `page` em vez de `novo_contexto`, e calculando "ontem").
    CHAMADA_ANTIGA = '''            print(f"Novidade encontrada no Data Much! Última atualização lá: {data_datamuch}")
            novo_contexto = coletar_contexto(frame)
            gmv_diario_novo = atualizar_gmv_diario(historico_atual.get("gmv_diario_mes", []), novo_contexto)
            atualizar_arquivos(novo_contexto, gmv_diario_novo, data_datamuch, novo_dia_detectado=True)
            escrever_output("mudou", "true")'''

    CHAMADA_NOVA = '''            print(f"Novidade encontrada no Data Much! Última atualização lá: {data_datamuch}")
            novo_contexto = coletar_contexto(frame)
            ontem = (datetime.now(BR_TZ) - timedelta(days=1)).date()
            gmv_diario_novo = preencher_dias_faltantes_gmv_diario(page, historico_atual.get("gmv_diario_mes", []), ontem)
            atualizar_arquivos(novo_contexto, gmv_diario_novo, data_datamuch, novo_dia_detectado=True)
            escrever_output("mudou", "true")'''

    texto = aplicar(texto, CHAMADA_ANTIGA, CHAMADA_NOVA, "chamada em main()")

    SCRIPT_PATH.write_text(texto, encoding="utf-8")
    print(f"Gravado {SCRIPT_PATH}")


if __name__ == "__main__":
    main()
