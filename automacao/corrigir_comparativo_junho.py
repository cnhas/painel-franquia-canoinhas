"""
Script de correcao pontual (rodar 1x): completa o comparativo com o mesmo dia
do mes anterior para os dias 16, 17, 18 e 19/07/2026 (o dia 15 ja tinha sido
preenchido antes). Guilherme pediu pra coletar TODOS os dias de junho
correspondentes, pra o comparativo funcionar pra qualquer dia selecionado no
painel, nao so pro dia 15.

Dados coletados manualmente em 21/07/2026 direto do Data Much
(Analises | Franquia > Acompanhamento de Operacao), usando o filtro de Data
com o MESMO dia no campo "de" e "ate" (ex: 16/06/2026 a 16/06/2026) pra
isolar o GMV Realizado e a Meta de cada dia individualmente:

  16/06/2026: GMV R$ 9.923,38  | Meta R$ 11.286,00
  17/06/2026: GMV R$ 11.981,47 | Meta R$ 13.366,00
  18/06/2026: GMV R$ 13.191,05 | Meta R$ 13.012,00
  19/06/2026: GMV R$ 24.488,09 | Meta R$ 26.250,00

O GMV de julho pra cada dia (16-19) ja estava correto em dias[] (vem do
scraper diario do Data Much) - so faltava o campo comparativo_mes_anterior
com o valor do mesmo dia de junho, pra bater com o que renderCompare() em
index.html espera (dia_mes_anterior, gmv_mes_anterior, meta_mes_anterior,
variacao_pct).

NAO mexe nos dias 20/07 em diante (ainda nao tem entrada detalhada em
dias[] - isso e' uma pendencia separada, ligada a nao ter uma coleta diaria
automatizada rodando pra alem do dia 19 ainda).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

# data_julho -> (gmv_mes_anterior, meta_mes_anterior, data_mes_anterior)
COMPARATIVOS_NOVOS = {
    "2026-07-16": (9923.38, 11286, "2026-06-16"),
    "2026-07-17": (11981.47, 13366, "2026-06-17"),
    "2026-07-18": (13191.05, 13012, "2026-06-18"),
    "2026-07-19": (24488.09, 26250, "2026-06-19"),
}


def substituir_bloco_json(texto: str, chave: str, novo_valor_json: str) -> str:
    """Acha "chave": <json> (objeto {} ou array []) e substitui pelo novo
    valor, usando JSONDecoder.raw_decode pra achar o fim exato do valor
    antigo (robusto contra colchetes/chaves aninhadas dentro do valor)."""
    marcador = f'"{chave}":'
    pos_chave = texto.find(marcador)
    if pos_chave == -1:
        raise RuntimeError(f"Nao encontrei a chave \"{chave}\" no arquivo.")
    i = pos_chave + len(marcador)
    while i < len(texto) and texto[i] in " \n\r\t":
        i += 1
    if i >= len(texto) or texto[i] not in "{[":
        raise RuntimeError(f"Esperava um objeto/array logo depois de \"{chave}\": mas achei {texto[i:i+30]!r}")
    decoder = json.JSONDecoder()
    _, fim_valor_antigo = decoder.raw_decode(texto, i)
    return texto[:pos_chave] + f'"{chave}": {novo_valor_json}' + texto[fim_valor_antigo:]


def main():
    historico = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
    dias = historico["dias"]

    algum_mudou = False
    for dia in dias:
        data_dia = dia.get("data")
        if data_dia not in COMPARATIVOS_NOVOS:
            continue
        if "comparativo_mes_anterior" in dia:
            print(f"{data_dia}: ja tinha comparativo_mes_anterior - nao mexi.")
            continue
        gmv_mes_anterior, meta_mes_anterior, data_mes_anterior = COMPARATIVOS_NOVOS[data_dia]
        gmv_dia = dia.get("gmv_dia")
        if gmv_dia is None:
            print(f"::warning::{data_dia} nao tem gmv_dia - pulando (nao consigo calcular variacao).")
            continue
        variacao_pct = round((gmv_dia / gmv_mes_anterior - 1) * 100, 2)
        dia["comparativo_mes_anterior"] = {
            "dia_mes_anterior": data_mes_anterior,
            "gmv_mes_anterior": gmv_mes_anterior,
            "meta_mes_anterior": meta_mes_anterior,
            "variacao_pct": variacao_pct,
        }
        algum_mudou = True
        print(f"Adicionado comparativo_mes_anterior em {data_dia}: "
              f"gmv_mes_anterior={gmv_mes_anterior}, variacao_pct={variacao_pct}%")

    if not algum_mudou:
        print("Nenhuma mudanca necessaria - todos os dias alvo ja tinham comparativo_mes_anterior.")
        return

    dias_json = json.dumps(dias, ensure_ascii=False, indent=2)

    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} nao encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto = substituir_bloco_json(texto, "dias", dias_json)
        path.write_text(texto, encoding="utf-8")
        print(f"Atualizado dias[] em {path}")


if __name__ == "__main__":
    main()
