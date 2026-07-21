"""
Script de correcao pontual (rodar 1x): corrige uma inconsistencia real
encontrada ao validar a 1a rodada do scraper automatico de
comparativo_mes_anterior (rodada de teste do dia 19/07/2026, workflow
"Atualizar dias" #14, 21/07/2026).

BUG REAL: coletar_comparativo_mes_anterior() (em automacao/scrape_dia_datamuch.py)
recalculava o GMV de "hoje" direto do report/208 (Acompanhamento de Operacao)
so pra montar a variacao_pct - mas esse valor pode diferir um pouco do gmv_dia
OFICIAL (que vem de gmv_diario_mes, a mesma fonte usada em todo o resto do
painel, inclusive no card "GMV hoje"). Resultado real: pro dia 19/07, o
comparativo automatico saiu com variacao_pct=-25.4% (usando um GMV relido de
~R$18.268,04), mas o gmv_dia oficial e' R$18.339,61, que da' -25.11% (o mesmo
valor ja validado manualmente antes). Isso e exatamente o tipo de
inconsistencia que Guilherme pediu pra nunca existir no painel: duas partes
do painel mostrando dois GMVs diferentes pro mesmo dia.

Correcao (2 partes):
  1) Em scrape_dia_datamuch.py: coletar_comparativo_mes_anterior() para de
     re-ler o GMV de hoje - so coleta o gmv/meta do MES ANTERIOR (que nao tem
     outra fonte). O calculo de variacao_pct e' movido pra main(), depois que
     o gmv_dia oficial (de gmv_diario_mes) ja foi resolvido - garantindo que a
     % sempre bate com o "GMV hoje" oficial. Se o gmv_dia oficial ainda nao
     estiver disponivel quando o comparativo for coletado, o bloco inteiro e'
     descartado (com uma pendencia) em vez de gravar um numero que pode estar
     errado.
  2) Corrige o dado ja gravado do dia 2026-07-19 (variacao_pct de -25.4 para
     -25.11, usando o gmv_dia oficial 18339.61 vs gmv_mes_anterior 24488.09).
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "automacao" / "scrape_dia_datamuch.py"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"


def aplicar(texto: str, antigo: str, novo: str, nome: str) -> str:
    if antigo not in texto:
        print(f"::warning::[{nome}] trecho antigo nao encontrado - talvez ja corrigido. Pulando.")
        return texto
    texto = texto.replace(antigo, novo, 1)
    print(f"Corrigido: {nome}")
    return texto


def corrigir_script():
    if not SCRIPT_PATH.exists():
        print(f"::error::{SCRIPT_PATH} nao encontrado.")
        return
    texto = SCRIPT_PATH.read_text(encoding="utf-8")

    ANTIGO_FUNCAO = '''def coletar_comparativo_mes_anterior(page, dia: date) -> dict:
    """Pra um dia X, coleta GMV/Meta do proprio dia X e do mesmo dia no mes
    anterior via report/208 (Acompanhamento de Operacao), e retorna o bloco
    comparativo_mes_anterior pronto pra gravar em dias[]."""
    primeiro_dia_mes_atual = dia.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    dia_no_mes_anterior = min(dia.day, ultimo_dia_mes_anterior.day)
    data_mes_anterior = ultimo_dia_mes_anterior.replace(day=dia_no_mes_anterior)

    frame_operacao = obter_frame(page, URL_OPERACAO)
    selecionar_dia_unico_sem_filtro(frame_operacao, data_mes_anterior)
    gmv_mes_anterior, meta_mes_anterior = ler_gmv_meta_dia_unico(frame_operacao)

    frame_operacao2 = obter_frame(page, URL_OPERACAO)
    selecionar_dia_unico_sem_filtro(frame_operacao2, dia)
    gmv_dia, _meta_dia = ler_gmv_meta_dia_unico(frame_operacao2)

    variacao_pct = round((gmv_dia / gmv_mes_anterior - 1) * 100, 2) if gmv_mes_anterior else None

    return {
        "dia_mes_anterior": data_mes_anterior.strftime("%Y-%m-%d"),
        "gmv_mes_anterior": gmv_mes_anterior,
        "meta_mes_anterior": meta_mes_anterior,
        "variacao_pct": variacao_pct,
    }'''

    NOVO_FUNCAO = '''def coletar_comparativo_mes_anterior(page, dia: date) -> dict:
    """Pra um dia X, coleta GMV/Meta do MESMO DIA no mes anterior via
    report/208 (Acompanhamento de Operacao). NAO re-coleta o GMV do proprio
    dia X aqui - o valor "oficial" de gmv_dia vem de outra fonte
    (gmv_diario_mes, a mesma usada no resto do painel) e e' aplicado depois,
    em main(), pra garantir que a % de variacao sempre bate com o "GMV hoje"
    mostrado no resto do painel.

    BUG REAL encontrado em 21/07/2026: a versao anterior desta funcao tambem
    relia o GMV de "hoje" direto do report/208 pra calcular a variacao_pct
    aqui mesmo - mas esse valor pode diferir um pouco do gmv_dia oficial
    (dia 19/07: -25.4% usando o GMV relido do report/208, contra -25.11%
    usando o gmv_dia oficial de R$18.339,61 - a diferenca veio do Power BI
    ter atualizado os dados "mes atual" entre a 1a coleta do dia e agora)."""
    primeiro_dia_mes_atual = dia.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    dia_no_mes_anterior = min(dia.day, ultimo_dia_mes_anterior.day)
    data_mes_anterior = ultimo_dia_mes_anterior.replace(day=dia_no_mes_anterior)

    frame_operacao = obter_frame(page, URL_OPERACAO)
    selecionar_dia_unico_sem_filtro(frame_operacao, data_mes_anterior)
    gmv_mes_anterior, meta_mes_anterior = ler_gmv_meta_dia_unico(frame_operacao)

    return {
        "dia_mes_anterior": data_mes_anterior.strftime("%Y-%m-%d"),
        "gmv_mes_anterior": gmv_mes_anterior,
        "meta_mes_anterior": meta_mes_anterior,
    }'''

    texto = aplicar(texto, ANTIGO_FUNCAO, NOVO_FUNCAO, "coletar_comparativo_mes_anterior sem re-ler GMV de hoje")

    ANTIGO_MAIN = '''                try:
                    novo_dia = coletar_dia(page, dia)
                    gmv, meta = _buscar_gmv_meta(historico_atual, novo_dia["data"])
                    if gmv is not None:
                        novo_dia["gmv_dia"] = gmv
                        novo_dia["meta_dia"] = meta
                    dias_atual = upsert_dia(dias_atual, novo_dia)
                    algum_sucesso = True
                except (PlaywrightTimeoutError, RuntimeError) as e:'''

    NOVO_MAIN = '''                try:
                    novo_dia = coletar_dia(page, dia)
                    gmv, meta = _buscar_gmv_meta(historico_atual, novo_dia["data"])
                    if gmv is not None:
                        novo_dia["gmv_dia"] = gmv
                        novo_dia["meta_dia"] = meta
                    # Fecha o calculo de variacao_pct do comparativo_mes_anterior
                    # usando o gmv_dia OFICIAL (mesma fonte do resto do painel) -
                    # nunca um valor relido do report/208 - pra nunca mostrar uma
                    # % que nao bate com o "GMV hoje" exibido em outro lugar do
                    # painel (bug real corrigido em 21/07/2026).
                    comp = novo_dia.get("comparativo_mes_anterior")
                    if comp is not None:
                        gmv_mes_ant = comp.get("gmv_mes_anterior")
                        if gmv is not None and gmv_mes_ant:
                            comp["variacao_pct"] = round((gmv / gmv_mes_ant - 1) * 100, 2)
                        else:
                            # Sem gmv_dia oficial ainda - descarta o comparativo
                            # nesta rodada em vez de gravar uma % que pode estar
                            # errada.
                            del novo_dia["comparativo_mes_anterior"]
                            novo_dia.setdefault("pendencias", []).append(
                                "Comparativo com o mesmo dia do mês anterior coletado, mas o "
                                "GMV oficial de hoje ainda não estava disponível pra calcular a "
                                "variação % com segurança — fica pendente pra próxima rodada."
                            )
                    dias_atual = upsert_dia(dias_atual, novo_dia)
                    algum_sucesso = True
                except (PlaywrightTimeoutError, RuntimeError) as e:'''

    texto = aplicar(texto, ANTIGO_MAIN, NOVO_MAIN, "fecha variacao_pct em main() com gmv_dia oficial")

    SCRIPT_PATH.write_text(texto, encoding="utf-8")
    print(f"Gravado {SCRIPT_PATH}")


def substituir_bloco_json(texto: str, chave: str, novo_valor_json: str) -> str:
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


def corrigir_dado_19_07():
    historico = json.loads(HISTORICO_JSON_PATH.read_text(encoding="utf-8"))
    dias = historico["dias"]
    alvo = None
    for dia in dias:
        if dia.get("data") == "2026-07-19":
            alvo = dia
            break
    if alvo is None:
        print("::warning::Nao achei a entrada de 2026-07-19 em dias[] - pulando correcao de dado.")
        return

    comp = alvo.get("comparativo_mes_anterior")
    gmv_dia = alvo.get("gmv_dia")
    if comp is None or gmv_dia is None:
        print("::warning::2026-07-19 nao tem comparativo_mes_anterior ou gmv_dia - pulando.")
        return

    gmv_mes_anterior = comp["gmv_mes_anterior"]
    variacao_correta = round((gmv_dia / gmv_mes_anterior - 1) * 100, 2)
    if comp.get("variacao_pct") == variacao_correta:
        print(f"2026-07-19: variacao_pct ja esta correta ({variacao_correta}%) - nao mexi.")
        return

    antiga = comp.get("variacao_pct")
    comp["variacao_pct"] = variacao_correta
    print(f"2026-07-19: variacao_pct corrigida de {antiga}% para {variacao_correta}% "
          f"(gmv_dia oficial={gmv_dia}, gmv_mes_anterior={gmv_mes_anterior}).")

    dias_json = json.dumps(dias, ensure_ascii=False, indent=2)
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        texto = path.read_text(encoding="utf-8")
        texto = substituir_bloco_json(texto, "dias", dias_json)
        path.write_text(texto, encoding="utf-8")
        print(f"Atualizado dias[] em {path}")


def main():
    corrigir_script()
    corrigir_dado_19_07()


if __name__ == "__main__":
    main()
