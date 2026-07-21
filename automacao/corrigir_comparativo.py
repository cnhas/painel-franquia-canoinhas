"""
Script de correcao pontual (rodar 1x): corrige o bug real que o Guilherme
reportou em 21/07/2026 - "o comparativo com o mesmo dia do mes anterior ainda
aparece dia 15" mesmo quando outro dia esta selecionado no painel.

Causa raiz confirmada lendo index.html: renderCompare() sempre lia
dataStore.comparativo_mes_anterior (um objeto GLOBAL fixo com os dados de
15/06 vs 15/07), nunca o dia selecionado. Alem disso, o listener de mudanca
do <select> so chamava renderDay(), nunca renderCompare() - entao a secao
NUNCA atualizava ao trocar de dia, nem que os dados fossem por dia.

Corrige:
1. Move os dados reais (que sao verdadeiros, so ficavam no lugar errado) pro
   campo comparativo_mes_anterior DENTRO da entrada do dia 15/07 em dias[].
2. Reescreve renderCompare() pra ler do dia selecionado, com fallback honesto
   ("sem dado ainda") quando o dia nao tiver essa comparacao coletada -
   em vez de mostrar (errado) os numeros do dia 15 pra qualquer dia.
3. Corrige o listener do <select> pra chamar renderCompare() tambem.
4. Deixa a secao de Investimentos mais honesta sobre o quanto esta
   desatualizada (dados de cupom franquia parados em 16/07).

NAO inventa dados novos pra dias 16-20/07 nem pra investimentos - isso
precisa de uma nova coleta no Data Much (ver mensagem enviada ao Guilherme).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"
HISTORICO_JSON_PATH = REPO_ROOT / "historico_vendas.json"


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

    dia15 = next((d for d in dias if d["data"] == "2026-07-15"), None)
    if dia15 is None:
        print("::error::Nao achei o dia 2026-07-15 em dias[] - abortando.")
        return

    if "comparativo_mes_anterior" not in dia15:
        dia15["comparativo_mes_anterior"] = {
            "dia_mes_anterior": "2026-06-15",
            "gmv_mes_anterior": 7985.49,
            "meta_mes_anterior": 10828,
            "variacao_pct": 52.19,
        }
        print("Adicionado comparativo_mes_anterior na entrada do dia 15/07.")
    else:
        print("dia 15/07 ja tinha comparativo_mes_anterior - nao mexi.")

    dias_json = json.dumps(dias, ensure_ascii=False, indent=2)

    investimentos = historico.get("investimentos")
    if investimentos:
        investimentos["verificacao_dados_recentes"] = (
            "ATENCAO (nota adicionada em 21/07/2026): os componentes de Cupom (subsidio "
            "franquia direto e 50% do compartilhado) cobrem SO ATE 16/07 - nao foram "
            "recoletados desde entao. Os componentes de Ofertas De/Por e Entrega "
            "promocional usam filtro 'mes completo', entao tenderiam a refletir dias novos "
            "automaticamente, mas o valor aqui ainda e o congelado de 17/07/2026 - precisa "
            "de uma nova coleta pra confirmar se mudou. Resumindo: os numeros desta secao "
            "NAO estao confirmados como atualizados ate hoje - tratar como referencia de "
            "meados de julho (01-16), nao como total do mes inteiro."
        )
        investimentos_json = json.dumps(investimentos, ensure_ascii=False, indent=2)
    else:
        investimentos_json = None

    for path in (INDEX_HTML_PATH, HISTORICO_JSON_PATH):
        if not path.exists():
            print(f"Aviso: {path} nao encontrado, pulando.")
            continue
        texto = path.read_text(encoding="utf-8")
        texto = substituir_bloco_json(texto, "dias", dias_json)
        if investimentos_json:
            texto = substituir_bloco_json(texto, "investimentos", investimentos_json)
        path.write_text(texto, encoding="utf-8")
        print(f"Atualizado dias[]/investimentos em {path}")

    # Agora corrige o JS de renderCompare() e o listener - so em index.html.
    texto = INDEX_HTML_PATH.read_text(encoding="utf-8")

    TRECHO_FN_ANTIGO = '''function renderCompare(){
  const c = dataStore.comparativo_mes_anterior;
  document.getElementById('momCompare').innerHTML = `
    <div class="kpi">
      <div class="value">${fmtMoney(c.dia_15_junho.gmv)}</div>
      <div class="label">15/06/2026 (mês anterior)</div>
      <div class="sub">Meta: ${fmtMoney(c.dia_15_junho.meta)}</div>
    </div>
    <div class="kpi">
      <div class="value">${fmtMoney(c.dia_15_julho.gmv)}</div>
      <div class="label">15/07/2026 (dia atual)</div>
      <div class="sub">Meta: ${fmtMoney(c.dia_15_julho.meta)}</div>
    </div>
    <div class="kpi navy">
      <div class="value">${fmtPct(c.variacao_pct)}</div>
      <div class="label">Variação no mesmo dia</div>
      <div class="sub good">Dia 15 cresceu bem mês a mês</div>
    </div>
  `;
}'''

    TRECHO_FN_NOVO = '''function renderCompare(){
  const d = dataStore.dias[daySelect.value];
  const c = d.comparativo_mes_anterior;
  const box = document.getElementById('momCompare');
  if(!c){
    box.innerHTML = `<div class="note" style="grid-column:1/-1;">Sem comparativo com o mesmo dia do mês anterior para ${daySelect.options[daySelect.selectedIndex].textContent} ainda — pendência de coleta.</div>`;
    return;
  }
  const [ay,am,ad] = c.dia_mes_anterior.split('-');
  const [by,bm,bd] = d.data.split('-');
  box.innerHTML = `
    <div class="kpi">
      <div class="value">${fmtMoney(c.gmv_mes_anterior)}</div>
      <div class="label">${ad}/${am}/${ay} (mês anterior)</div>
      <div class="sub">Meta: ${fmtMoney(c.meta_mes_anterior)}</div>
    </div>
    <div class="kpi">
      <div class="value">${fmtMoney(d.gmv_dia)}</div>
      <div class="label">${bd}/${bm}/${by} (dia selecionado)</div>
      <div class="sub">Meta: ${fmtMoney(d.meta_dia)}</div>
    </div>
    <div class="kpi navy">
      <div class="value">${fmtPct(c.variacao_pct)}</div>
      <div class="label">Variação no mesmo dia</div>
      <div class="sub ${c.variacao_pct>=0?'good':'warn'}">${c.variacao_pct>=0?'Cresceu':'Caiu'} mês a mês</div>
    </div>
  `;
}'''

    if TRECHO_FN_ANTIGO not in texto:
        print("::warning::renderCompare() antigo nao encontrado como esperado - talvez ja corrigido. Pulando.")
    else:
        texto = texto.replace(TRECHO_FN_ANTIGO, TRECHO_FN_NOVO, 1)
        print("Corrigido: renderCompare() agora le do dia selecionado, com fallback honesto.")

    TRECHO_LISTENER_ANTIGO = "daySelect.addEventListener('change', renderDay);"
    TRECHO_LISTENER_NOVO = "daySelect.addEventListener('change', ()=>{ renderDay(); renderCompare(); });"
    if TRECHO_LISTENER_ANTIGO not in texto:
        print("::warning::listener antigo do daySelect nao encontrado - talvez ja corrigido. Pulando.")
    else:
        texto = texto.replace(TRECHO_LISTENER_ANTIGO, TRECHO_LISTENER_NOVO, 1)
        print("Corrigido: trocar de dia agora tambem atualiza o comparativo com mes anterior.")

    INDEX_HTML_PATH.write_text(texto, encoding="utf-8")
    print("Gravado index.html com as correcoes de JS.")


if __name__ == "__main__":
    main()
