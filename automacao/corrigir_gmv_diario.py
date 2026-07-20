"""
Script de correção pontual (rodar 1x): substitui o dia 17/07 inflado (que tinha acumulado
o delta de 4 dias — 16, 17, 18 e 19 — por causa do bug de "um dia só" no scraper antigo)
pelos 4 dias corretos, com valores confirmados via hover no gráfico "GMV Diário - período
selecionado" do Data Much (report/208), filtrado pra 15/07-19/07/2026. A soma bate exato
com o card "GMV" do período (R$ 77.745,53 = 12153,49 + 10908,89 + 15019,46 + 21324,08 +
18339,61), então os valores estão confirmados corretos.

Depois de rodar, NÃO precisa rodar de novo — é uma correção histórica pontual, não parte
da rotina diária normal.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

DIAS_CORRETOS = [
    {"data": "2026-07-16", "gmv": 10908.89, "meta": 12910},
    {"data": "2026-07-17", "gmv": 15019.46, "meta": 20567},
    {"data": "2026-07-18", "gmv": 21324.08, "meta": 21037},
    {"data": "2026-07-19", "gmv": 18339.61, "meta": 18314},
]


def main():
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        padrao_dia_17_errado = r'\{"data":\s*"2026-07-17",\s*"gmv":\s*65352\.84,\s*"meta":\s*15633\}'
        substituicao = ", ".join(
            f'{{"data": "{d["data"]}", "gmv": {d["gmv"]}, "meta": {d["meta"]}}}'
            for d in DIAS_CORRETOS
        )
        texto_novo, n = re.subn(padrao_dia_17_errado, substituicao, texto, count=1)
        if n == 0:
            print(f"::warning::Não achei o bloco do dia 17 inflado em {path} — talvez já tenha sido corrigido.")
            continue
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Corrigido: {path}")


if __name__ == "__main__":
    main()
