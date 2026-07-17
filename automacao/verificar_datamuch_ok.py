"""
Pre-check leve (sem Playwright) rodado ANTES de instalar/abrir o navegador.

O Data Much só atualiza 1x por dia (em horário variável, geralmente entre 7h30 e o
início da tarde). Assim que uma execução acha a atualização do dia, não faz sentido
gastar tempo (e minutos do GitHub Actions) abrindo navegador de novo nas checagens
seguintes do mesmo dia — este script lê o "verificado_ok_data" salvo pela última
execução que encontrou novidade e compara com a data de hoje (fuso de Brasília).

Escreve "pular=true" ou "pular=false" no $GITHUB_OUTPUT. O workflow condiciona os
passos de instalar Playwright / rodar o scraper / deploy / commit a "pular != 'true'".
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

BR_TZ = timezone(timedelta(hours=-3))
REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"


def main():
    hoje = datetime.now(BR_TZ).strftime("%Y-%m-%d")
    verificado_ok_data = ""
    try:
        dados = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
        verificado_ok_data = dados.get("data_much_status", {}).get("verificado_ok_data", "")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Aviso: não consegui ler {HISTORICO_JSON_PATH} ({e}) — seguindo sem pular.")

    pular = verificado_ok_data == hoje
    print(f"Hoje (Brasília): {hoje} | Já verificado OK em: {verificado_ok_data!r} | Pular: {pular}")

    caminho_output = os.environ.get("GITHUB_OUTPUT")
    if caminho_output:
        with open(caminho_output, "a", encoding="utf-8") as f:
            f.write(f"pular={'true' if pular else 'false'}\n")


if __name__ == "__main__":
    main()
