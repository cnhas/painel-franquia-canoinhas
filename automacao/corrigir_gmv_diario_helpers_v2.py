"""
Script de correcao pontual (rodar 1x): completa o patch de
corrigir_gmv_diario_mensal_rollover.py, que rodou parcialmente (3 das 4
alteracoes aplicaram certo; a insercao das funcoes auxiliares - _esperar,
_fechar_overlay_calendario, obter_frame_dia_unico, selecionar_dia_unico_sem_filtro,
ler_gmv_meta_dia_unico - falhou com "trecho antigo nao encontrado", porque o
ancora usado (bloco de 2 funcoes com 1 linha em branco entre elas) nao batia
com o arquivo real, que tem 2 linhas em branco entre funcoes de nivel
superior - PEP8 padrao). Isso deixou preencher_dias_faltantes_gmv_diario()
chamando obter_frame_dia_unico() sem essa funcao existir, quebrando a
primeira tentativa de backfill (run #379 do workflow "Atualizar Data Much",
NameError: name 'obter_frame_dia_unico' is not defined).

Este script usa uma ancora mais simples e robusta (so a linha
"def login_datamuch(page):", unica no arquivo) pra inserir as 5 funcoes
faltantes logo antes dela.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "automacao" / "scrape_datamuch.py"

ANCORA = "def login_datamuch(page):"

FUNCOES_NOVAS = '''def _esperar(frame, ms: int):
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


def selecionar_dia_unico_sem_filtro(frame, dia):
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


def ler_gmv_meta_dia_unico(frame):
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


'''


def main():
    if not SCRIPT_PATH.exists():
        print(f"::error::{SCRIPT_PATH} nao encontrado.")
        return
    texto = SCRIPT_PATH.read_text(encoding="utf-8")

    if "def obter_frame_dia_unico(" in texto:
        print("Já tem obter_frame_dia_unico() - talvez já corrigido. Pulando.")
        return

    if ANCORA not in texto:
        print(f"::error::Âncora {ANCORA!r} não encontrada em {SCRIPT_PATH}.")
        return

    texto_novo = texto.replace(ANCORA, FUNCOES_NOVAS + ANCORA, 1)
    SCRIPT_PATH.write_text(texto_novo, encoding="utf-8")
    print(f"Gravado {SCRIPT_PATH} - funções auxiliares inseridas antes de {ANCORA!r}.")


if __name__ == "__main__":
    main()

