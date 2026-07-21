"""
Script de correcao pontual (rodar 1x): scrape_pedidos.py esta falhando desde
20/07/2026 ~21h15 (Brasilia) com "Timeout esperando elemento", especificamente
esperando o texto "Exibindo X a Y de Z resultados" aparecer na pagina de
Historico do Painel Delivery Much.

Sem acesso a sessao logada, nao da pra confirmar com certeza qual seletor
mudou. Em vez de adivinhar as cegas, este script adiciona diagnostico real:
no momento da falha, salva uma screenshot E o HTML completo da pagina como
artefato do workflow, pra proxima falha a gente conseguir ver exatamente o
que a pagina estava mostrando.

Muda dois arquivos:
1. automacao/scrape_pedidos.py - no bloco except PlaywrightTimeoutError,
   alem do screenshot que ja existia, salva tambem page.content() em
   erro_debug.html.
2. .github/workflows/atualizar-painel.yml - adiciona um step
   "if: failure()" que sobe erro_debug.png/html e erro_login.png/html
   como artifact do GitHub Actions.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPE_PEDIDOS_PATH = REPO_ROOT / "automacao" / "scrape_pedidos.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "atualizar-painel.yml"

TRECHO_PY_ANTIGO = '''        except PlaywrightTimeoutError as e:
            print(f"::error::Timeout esperando elemento - provavelmente um seletor mudou: {e}")
            page.screenshot(path="erro_debug.png")
            sys.exit(1)
        except RuntimeError as e:
            print(f"::error::{e}")
            page.screenshot(path="erro_login.png")
            sys.exit(1)'''

TRECHO_PY_NOVO = '''        except PlaywrightTimeoutError as e:
            print(f"::error::Timeout esperando elemento - provavelmente um seletor mudou: {e}")
            page.screenshot(path="erro_debug.png")
            try:
                Path("erro_debug.html").write_text(page.content(), encoding="utf-8")
            except Exception as e2:
                print(f"::warning::Nao consegui salvar erro_debug.html: {e2}")
            sys.exit(1)
        except RuntimeError as e:
            print(f"::error::{e}")
            page.screenshot(path="erro_login.png")
            try:
                Path("erro_login.html").write_text(page.content(), encoding="utf-8")
            except Exception as e2:
                print(f"::warning::Nao consegui salvar erro_login.html: {e2}")
            sys.exit(1)'''

TRECHO_YML_ANTIGO = '''      - name: Coletar pedidos e atualizar arquivos
        env:
          PAINEL_EMAIL: ${{ secrets.PAINEL_EMAIL }}
          PAINEL_SENHA: ${{ secrets.PAINEL_SENHA }}
        run: python automacao/scrape_pedidos.py

      - name: Preparar pasta de publicacao'''

TRECHO_YML_NOVO = '''      - name: Coletar pedidos e atualizar arquivos
        env:
          PAINEL_EMAIL: ${{ secrets.PAINEL_EMAIL }}
          PAINEL_SENHA: ${{ secrets.PAINEL_SENHA }}
        run: python automacao/scrape_pedidos.py

      - name: Upload diagnostico em caso de falha
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: erro-debug-pedidos
          path: |
            erro_debug.png
            erro_debug.html
            erro_login.png
            erro_login.html
          if-no-files-found: ignore
          retention-days: 7

      - name: Preparar pasta de publicacao'''


def main():
    if not SCRAPE_PEDIDOS_PATH.exists():
        print(f"::error::{SCRAPE_PEDIDOS_PATH} nao encontrado.")
    else:
        texto = SCRAPE_PEDIDOS_PATH.read_text(encoding="utf-8")
        if TRECHO_PY_ANTIGO not in texto:
            print("::warning::Bloco except nao encontrado, talvez ja corrigido. Pulando.")
        else:
            texto = texto.replace(TRECHO_PY_ANTIGO, TRECHO_PY_NOVO, 1)
            SCRAPE_PEDIDOS_PATH.write_text(texto, encoding="utf-8")
            print(f"Corrigido: {SCRAPE_PEDIDOS_PATH} agora salva HTML da pagina no momento da falha.")

    if not WORKFLOW_PATH.exists():
        print(f"::error::{WORKFLOW_PATH} nao encontrado.")
    else:
        texto = WORKFLOW_PATH.read_text(encoding="utf-8")
        if TRECHO_YML_ANTIGO not in texto:
            print("::warning::Bloco do workflow nao encontrado, talvez ja corrigido. Pulando.")
        else:
            texto = texto.replace(TRECHO_YML_ANTIGO, TRECHO_YML_NOVO, 1)
            WORKFLOW_PATH.write_text(texto, encoding="utf-8")
            print(f"Corrigido: {WORKFLOW_PATH} agora sobe erro_debug.png/html como artifact quando o job falha.")


if __name__ == "__main__":
    main()
