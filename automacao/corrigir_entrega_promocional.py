"""
Script de correcao pontual (rodar 1x): reverte um numero ERRADO que acabou
de ser publicado no painel pela run #3 do workflow "Atualizar investimentos
da franquia" (21/07/2026).

BUG REAL: o componente "Entrega promocional - subsidio franquia" foi
gravado como R$92,80 - mas esse numero e' apenas o MAIOR valor de UMA loja
na coluna "entrega promocional - subsidio franquia" (depois de ordenar
decrescente), NAO a soma de todas as lojas. Ou seja, R$92,80 e' um piso
(o total real e' >= R$92,80), nao o total de verdade - gravar isso como se
fosse o total teria SUBESTIMADO o investimento real da franquia. O codigo
do scraper ja foi corrigido (agora recusa aceitar um valor > 0 como total,
caindo em pendencia em vez de gravar numero errado) - este script so
conserta o dado que ja tinha sido publicado antes da correcao do codigo.

Reverte esse componente pro estado anterior (R$0,00, o ultimo valor
"seguro" conhecido antes desta rodada com bug), com uma pendencia clara
explicando que o valor real e' desconhecido e precisa de verificacao manual
ou de uma futura versao do scraper que some a coluna inteira (nao so o
topo).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"

NOME_COMPONENTE = "Entrega promocional — subsídio franquia"


def substituir_bloco_json(texto: str, chave: str, novo_valor_json: str) -> str:
    marcador = f'"{chave}":'
    pos_chave = texto.find(marcador)
    if pos_chave == -1:
        raise RuntimeError(f"Não encontrei a chave \"{chave}\" no arquivo.")
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
    investimentos = historico.get("investimentos")
    if not investimentos:
        print("::warning::Não achei a seção investimentos - nada pra corrigir.")
        return

    componentes = investimentos.get("componentes", [])
    alvo = None
    for c in componentes:
        if c.get("nome") == NOME_COMPONENTE:
            alvo = c
            break

    if alvo is None:
        print(f"::warning::Não achei o componente \"{NOME_COMPONENTE}\" - nada pra corrigir.")
        return

    valor_errado = alvo.get("valor")
    if valor_errado in (0, 0.0, None):
        print(f"Componente já está em 0 (valor={valor_errado}) - nada pra corrigir.")
        return

    print(f"Corrigindo \"{NOME_COMPONENTE}\": valor errado gravado = R$ {valor_errado} "
          f"(era só o maior valor de 1 loja, não a soma de todas) -> revertendo pra R$ 0,00 "
          f"com pendência explícita, até termos uma soma de verdade.")

    alvo["valor"] = 0.0
    alvo["obs"] = (
        "Revertido em 21/07/2026: um valor de R$92,80 tinha sido gravado por engano (era o maior "
        "valor de 1 loja só, não a soma de todas as lojas). Até a automação somar a coluna inteira, "
        "fica em 0,00 com pendência explícita — NÃO necessariamente o valor real (pode ser > 0)."
    )

    # Recalcula o total_confirmado com o valor corrigido.
    total_confirmado = round(sum(c["valor"] for c in componentes), 2)
    investimentos["total_confirmado"] = total_confirmado

    pendencias = investimentos.get("pendencias", [])
    pendencias = [p for p in pendencias if "Entrega promocional" not in p and "entrega promocional" not in p]
    pendencias.insert(0,
        "\"Entrega promocional — subsídio franquia\": o valor real deste componente é DESCONHECIDO "
        "no momento (não é necessariamente 0) — a automação ainda só consegue detectar com segurança "
        "quando o total é 0 (todas as lojas zeradas); quando alguma loja tem valor > 0, ainda não "
        "soma a coluna inteira, então prefere não gravar um número que poderia estar errado."
    )
    investimentos["pendencias"] = pendencias

    print(f"total_confirmado recalculado: R$ {total_confirmado}")

    investimentos_json = json.dumps(investimentos, ensure_ascii=False, indent=2)
    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        texto = path.read_text(encoding="utf-8")
        texto_novo = substituir_bloco_json(texto, "investimentos", investimentos_json)
        json.loads(investimentos_json)
        if path == HISTORICO_JSON_PATH:
            json.loads(texto_novo)
        path.write_text(texto_novo, encoding="utf-8")
        print(f"Atualizado: {path}")


if __name__ == "__main__":
    main()
