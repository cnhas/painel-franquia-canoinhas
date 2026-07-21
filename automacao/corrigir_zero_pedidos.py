"""
Script de correcao pontual (rodar 1x): corrige o bug real por tras da falha de
21/07/2026 no scrape_pedidos.py. Confirmado com screenshot + HTML real (enviados
pelo Guilherme): quando NAO ha nenhum pedido no periodo, o #orders-table_info
(DataTables) mostra "Showing 0 to 0 of 0 entries" em INGLES (o site nunca
traduziu o "sInfoEmpty"), em vez do template em portugues "Exibindo X a Y de Z
resultados." que o script esperava. Isso fazia o script esperar pra sempre por
um texto que nunca aparece nesse caso, e estourar timeout de 45s.

Corrige coletar_pedidos_hoje() pra usar o id #orders-table_info (estavel nos
dois idiomas) em vez do texto, e tratar os dois formatos ao extrair o total.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPE_PEDIDOS_PATH = REPO_ROOT / "automacao" / "scrape_pedidos.py"

TRECHO_ANTIGO = '''    # Confirma o texto "Exibindo 1 a X de Y resultados." pra pegar o total.
    resumo_locator = page.get_by_text(re.compile(r"Exibindo \d+ a \d+ de \d+ resultados"))
    resumo_locator.wait_for(state="visible", timeout=NAV_TIMEOUT_MS)
    resumo = resumo_locator.inner_text()
    total_pedidos = int(re.search(r"de (\d+) resultados", resumo).group(1))'''

TRECHO_NOVO = '''    # #orders-table_info e o elemento de resumo do DataTables - usamos o id (estavel)
    # em vez do texto, porque o texto muda de idioma dependendo se ha resultados ou nao.
    # Com pedidos: "Exibindo 1 a 10 de 41 resultados." Sem pedidos (dia zerado): o site
    # nunca traduziu o sInfoEmpty, entao cai no padrao em ingles da lib DataTables:
    # "Showing 0 to 0 of 0 entries". Bug real descoberto em 21/07/2026 (causava timeout
    # eterno esperando um texto em portugues que nunca aparece quando o dia esta zerado).
    resumo_locator = page.locator("#orders-table_info")
    resumo_locator.wait_for(state="visible", timeout=NAV_TIMEOUT_MS)
    resumo = resumo_locator.inner_text()
    match_pt = re.search(r"de (\d+) resultados", resumo)
    match_en = re.search(r"of (\d+) entries", resumo)
    if match_pt:
        total_pedidos = int(match_pt.group(1))
    elif match_en:
        total_pedidos = int(match_en.group(1))
    else:
        raise RuntimeError(f"Nao consegui extrair o total de #orders-table_info: texto inesperado {resumo!r}")'''


def main():
    if not SCRAPE_PEDIDOS_PATH.exists():
        print(f"::error::{SCRAPE_PEDIDOS_PATH} nao encontrado.")
        return
    texto = SCRAPE_PEDIDOS_PATH.read_text(encoding="utf-8")
    if TRECHO_ANTIGO not in texto:
        print("::warning::Trecho esperado nao encontrado - talvez ja corrigido, ou o texto mudou. Nada foi alterado.")
        return
    texto = texto.replace(TRECHO_ANTIGO, TRECHO_NOVO, 1)
    SCRAPE_PEDIDOS_PATH.write_text(texto, encoding="utf-8")
    print("Corrigido: coletar_pedidos_hoje() agora trata corretamente dias com 0 pedidos (fallback em ingles do DataTables).")


if __name__ == "__main__":
    main()
