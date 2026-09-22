"""
Script de correcao de emergencia (rodar 1x): reverte entradas CORROMPIDAS de
gmv_diario_mes.

Contexto: em 22/09/2026, o backfill automatico via
preencher_dias_faltantes_gmv_diario() (nova logica anti-travamento) rodou
com sucesso pra Julho e Agosto (valores plausiveis, dia a dia, ~R$8mil-23mil),
mas PARA SETEMBRO (mes corrente) os valores lidos ficaram claramente errados:
crescentes e muito maiores que deveriam (R$464mil no dia 1, R$762mil no dia
21) - inclusive MAIORES que o total do mes inteiro (contexto_mensal.
gmv_realizado_mes = R$453595,52 em 22/09/2026), o que e logicamente
impossivel (um unico dia nao pode superar o total acumulado do mes).

Hipotese: o filtro de "dia unico" (selecionar_dia_unico_sem_filtro) nao
isola corretamente um unico dia quando a data esta dentro do MES CORRENTE
(ainda em andamento) - possivelmente a UI do Data Much intercepta com algum
preset/quick-select quando as datas estao proximas de "hoje", diferente do
comportamento pra meses ja fechados (Julho/Agosto), onde o filtro funcionou
perfeitamente.

Esta correcao REMOVE as entradas de Setembro (01 a 21) de gmv_diario_mes,
voltando o array a parar em 2026-08-31 (ultimo dado confiavel), ate que a
causa raiz do problema especifico de mes corrente seja identificada e
corrigida. Preferimos dados INCOMPLETOS a dados ERRADOS, conforme a
diretriz do usuario: nao faz sentido ter o painel com dados quebrados.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

CORTE_DATA = "2026-09-01"  # remove tudo >= essa data


def substituir_bloco_array(texto: str, chave: str, novo_valor_json: str) -> str:
    padrao = rf'"{chave}":\s*\[[^\[\]]*\]'
    return re.sub(padrao, f'"{chave}": {novo_valor_json}', texto, count=1, flags=re.DOTALL)


def main():
    historico = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
    gmv_diario = historico.get("gmv_diario_mes", [])

    antes = len(gmv_diario)
    corrompidos = [d for d in gmv_diario if d["data"] >= CORTE_DATA]
    gmv_diario_corrigido = [d for d in gmv_diario if d["data"] < CORTE_DATA]
    depois = len(gmv_diario_corrigido)

    if not corrompidos:
        print(f"Nenhuma entrada >= {CORTE_DATA} encontrada em gmv_diario_mes - talvez ja corrigido. Pulando.")
        return

    print(f"Removendo {antes - depois} entradas corrompidas de gmv_diario_mes (>= {CORTE_DATA}):")
    for d in corrompidos:
        print(f"  removido: {d['data']} gmv={d['gmv']} meta={d.get('meta')}")

    gmv_diario_json = json.dumps(gmv_diario_corrigido, ensure_ascii=False)

    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"::error::{path} nao encontrado.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto_novo = substituir_bloco_array(texto, "gmv_diario_mes", gmv_diario_json)
        if texto_novo == texto:
            print(f"::error::Nao consegui substituir gmv_diario_mes em {path} (padrao nao encontrado?).")
            continue
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Gravado {path} - gmv_diario_mes agora tem {depois} entradas (ate {gmv_diario_corrigido[-1]['data'] if gmv_diario_corrigido else 'N/A'}).")


if __name__ == "__main__":
    main()
