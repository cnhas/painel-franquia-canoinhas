"""
Script de correção pontual (rodar 1x): conserta o JSON de index.html e
historico_vendas.json, que ficou corrompido por um bug real no
scrape_dia_datamuch.py (regex não-gulosa "[.*?]" parava no primeiro colchete
de fechamento ANINHADO em vez do de fora, deixando um pedaço de conteúdo
antigo duplicado/pendurado logo depois do array "dias", fechando o objeto
raiz cedo demais e virando "Extra data" no fim do arquivo).

O bug em si já foi corrigido em substituir_bloco_array() (agora usa
json.JSONDecoder().raw_decode, que entende profundidade de colchetes de
verdade) — este script aqui só limpa a bagunça que a versão anterior já
tinha deixado no arquivo publicado.

Também aproveita pra remover a entrada do dia 19/07 do array "dias", porque
saiu com bug (ranking de lojas todo zerado e cupons_categoria/cupons_uso
vazios) — melhor não ter a entrada do que ter uma com dado errado. Assim que
o scraper de lojas/cupons estiver corrigido e testado, roda de novo pra
adicionar o dia 19 (e os outros) direito.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

DIAS_PARA_REMOVER = {"2026-07-19"}


def consertar(texto: str) -> str:
    marcador = '"dias":'
    pos_chave = texto.find(marcador)
    if pos_chave == -1:
        raise RuntimeError('Não achei a chave "dias" no arquivo.')

    i = pos_chave + len(marcador)
    while i < len(texto) and texto[i] in " \n\r\t":
        i += 1
    if i >= len(texto) or texto[i] != "[":
        raise RuntimeError(f'Esperava um array logo depois de "dias": mas achei {texto[i:i+30]!r}')

    decoder = json.JSONDecoder()
    dias_atual, fim_valor = decoder.raw_decode(texto, i)
    print(f"Array \"dias\" atual (válido) tem {len(dias_atual)} entrada(s): {[d.get('data') for d in dias_atual]}")

    # Acha onde a próxima chave de verdade ("investimentos") começa, depois
    # de qualquer lixo pendurado que tenha sobrado da versão corrompida.
    m = re.search(r'"investimentos"\s*:', texto[fim_valor:])
    if not m:
        raise RuntimeError('Não achei "investimentos" depois do array "dias" — não dá pra saber até onde limpar com segurança.')
    pos_investimentos = fim_valor + m.start()

    dias_corrigido = [d for d in dias_atual if d.get("data") not in DIAS_PARA_REMOVER]
    print(f"Array \"dias\" corrigido vai ficar com {len(dias_corrigido)} entrada(s): {[d.get('data') for d in dias_corrigido]}")

    dias_json = json.dumps(dias_corrigido, ensure_ascii=False, indent=2)
    novo_texto = texto[:pos_chave] + f'"dias": {dias_json},\n  ' + texto[pos_investimentos:]
    return novo_texto


def main():
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} não encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        try:
            novo_texto = consertar(texto)
        except RuntimeError as e:
            print(f"::warning::Não consegui consertar {path}: {e} (talvez já esteja corrigido)")
            continue

        # Checagem de segurança: só escreve se o resultado for JSON válido de
        # verdade. Pro index.html, o JSON está embutido dentro de <script> —
        # aqui testamos genericamente tentando achar e validar só o trecho
        # que injetamos (dias + o que vem depois até fechar razoavelmente).
        # Validação mais forte: tenta decodificar o arquivo inteiro como JSON
        # quando for o historico_vendas.json (que é JSON puro).
        if path == HISTORICO_JSON_PATH:
            try:
                json.loads(novo_texto)
            except json.JSONDecodeError as e:
                print(f"::error::Resultado ainda não é JSON válido pra {path}, não vou escrever. Erro: {e}")
                continue
            print(f"Validado: {path} agora é JSON válido.")

        path.write_text(novo_texto, encoding="utf-8")
        print(f"Corrigido: {path}")


if __name__ == "__main__":
    main()
