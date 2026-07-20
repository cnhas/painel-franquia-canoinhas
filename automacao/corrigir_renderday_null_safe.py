"""
Script de correção pontual (rodar 1x): corrige um bug real de JS em
index.html — renderDay() lia `d.painel.pedidos_totais` sem checar se
`d.painel` existe. Os dias novos criados pelo scraper automático
(scrape_dia_datamuch.py) NÃO incluem o campo "painel" (dados do Painel
Delivery Much ainda não são coletados por ele — pendência conhecida), então
ao selecionar qualquer um desses dias (16, 17, 18, 19/07 em diante) o
JavaScript lançava TypeError: "Cannot read properties of undefined (reading
'pedidos_totais')" e ABORTAVA o resto do renderDay() — por isso as seções
"Top 10 lojas", "Uso de cupons", "Cupons por categoria" e "Ofertas De/Por"
ficavam todas em branco na tela pra qualquer dia que não fosse 15/07.

Esse script torna renderDay() defensivo: painel vira opcional (mostra um
aviso em vez de quebrar), e cupons_uso/cupons_categoria/ofertas_de_por/
top_lojas_* também ganham fallback pra lista vazia, pra nunca mais travar o
render inteiro por causa de um campo faltando em UM dia.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "index.html"

BLOCO_ANTIGO = """  const p = d.painel;
  document.getElementById('painelKpis').innerHTML = `
    <div class="kpi navy">
      <div class="value">${fmtInt(p.pedidos_totais)}</div>
      <div class="label">Pedidos totais (Painel)</div>
      <div class="sub">Fonte autoritativa</div>
    </div>
    <div class="kpi navy">
      <div class="value">${fmtInt(p.cancelados)}</div>
      <div class="label">Pedidos cancelados</div>
      <div class="sub warn">${p.pct_cancelados.toFixed(1).replace('.',',')}% do total</div>
    </div>
    <div class="kpi navy">
      <div class="value">${fmtInt(p.entrega)}</div>
      <div class="label">Entregas</div>
      <div class="sub good">${(p.entrega/p.pedidos_totais*100).toFixed(1).replace('.',',')}% do total</div>
    </div>
    <div class="kpi navy">
      <div class="value">${fmtInt(p.retirada)}</div>
      <div class="label">Retirada no local</div>
      <div class="sub">${(p.retirada/p.pedidos_totais*100).toFixed(1).replace('.',',')}% do total</div>
    </div>
  `;

  renderLojas();

  const maxCupom = Math.max(...d.cupons_uso.map(c=>c.pedidos));
  document.getElementById('cuponsBars').innerHTML = d.cupons_uso.map(c=>`
    <div class="bar-row">
      <div class="bar-label">${c.codigo}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(c.pedidos/maxCupom*100).toFixed(0)}%"></div></div>
      <div class="bar-value">${c.pedidos}</div>
    </div>
  `).join('');

  document.getElementById('categoriaLines').innerHTML = d.cupons_categoria.map(c=>`
    <div class="stat-line"><span>${c.categoria}</span><b>${c.qtd}</b></div>
  `).join('');

  const o = d.ofertas_de_por;
  document.getElementById('ofertasBox').innerHTML = `
    <div class="kpis" style="margin-bottom:16px;">
      <div class="kpi">
        <div class="value">${fmtInt(o.itens_vendidos)}</div>
        <div class="label">Itens vendidos em oferta</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.gmv_produtos)}</div>
        <div class="label">GMV desses produtos</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.subsidio_franquia)}</div>
        <div class="label">Subsídio pago pela franquia</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.subsidio_loja)}</div>
        <div class="label">Subsídio pago pelas lojas</div>
      </div>
    </div>
    <div>${o.destaques.map(t=>`<span class="tag">${t}</span>`).join('')}</div>
  `;"""

BLOCO_NOVO = """  const p = d.painel;
  if(p){
    document.getElementById('painelKpis').innerHTML = `
      <div class="kpi navy">
        <div class="value">${fmtInt(p.pedidos_totais)}</div>
        <div class="label">Pedidos totais (Painel)</div>
        <div class="sub">Fonte autoritativa</div>
      </div>
      <div class="kpi navy">
        <div class="value">${fmtInt(p.cancelados)}</div>
        <div class="label">Pedidos cancelados</div>
        <div class="sub warn">${p.pct_cancelados.toFixed(1).replace('.',',')}% do total</div>
      </div>
      <div class="kpi navy">
        <div class="value">${fmtInt(p.entrega)}</div>
        <div class="label">Entregas</div>
        <div class="sub good">${(p.entrega/p.pedidos_totais*100).toFixed(1).replace('.',',')}% do total</div>
      </div>
      <div class="kpi navy">
        <div class="value">${fmtInt(p.retirada)}</div>
        <div class="label">Retirada no local</div>
        <div class="sub">${(p.retirada/p.pedidos_totais*100).toFixed(1).replace('.',',')}% do total</div>
      </div>
    `;
  } else {
    document.getElementById('painelKpis').innerHTML = `
      <div class="note" style="grid-column:1/-1;">
        Dados do Painel (pedidos totais/cancelados/entrega/retirada) ainda não disponíveis para este dia — a automação atual só cobre os relatórios do Data Much. Fica como pendência.
      </div>
    `;
  }

  renderLojas();

  const cuponsUso = d.cupons_uso || [];
  const maxCupom = cuponsUso.length ? Math.max(...cuponsUso.map(c=>c.pedidos)) : 0;
  document.getElementById('cuponsBars').innerHTML = cuponsUso.length ? cuponsUso.map(c=>`
    <div class="bar-row">
      <div class="bar-label">${c.codigo}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${maxCupom ? (c.pedidos/maxCupom*100).toFixed(0) : 0}%"></div></div>
      <div class="bar-value">${c.pedidos}</div>
    </div>
  `).join('') : '<div class="note">Sem dados de uso de cupons por campanha para este dia.</div>';

  const cuponsCategoria = d.cupons_categoria || [];
  document.getElementById('categoriaLines').innerHTML = cuponsCategoria.length ? cuponsCategoria.map(c=>`
    <div class="stat-line"><span>${c.categoria}</span><b>${c.qtd}</b></div>
  `).join('') : '<div class="note">Sem dados de cupons por categoria para este dia.</div>';

  const o = d.ofertas_de_por;
  document.getElementById('ofertasBox').innerHTML = o ? `
    <div class="kpis" style="margin-bottom:16px;">
      <div class="kpi">
        <div class="value">${fmtInt(o.itens_vendidos)}</div>
        <div class="label">Itens vendidos em oferta</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.gmv_produtos)}</div>
        <div class="label">GMV desses produtos</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.subsidio_franquia)}</div>
        <div class="label">Subsídio pago pela franquia</div>
      </div>
      <div class="kpi">
        <div class="value">${fmtMoney(o.subsidio_loja)}</div>
        <div class="label">Subsídio pago pelas lojas</div>
      </div>
    </div>
    <div>${(o.destaques||[]).map(t=>`<span class="tag">${t}</span>`).join('')}</div>
  ` : '<div class="note">Sem dados de Ofertas De/Por para este dia.</div>';"""

BLOCO_LOJAS_ANTIGO = """function renderLojas(){
  const d = dataStore.dias[daySelect.value];
  const list = lojaMode === 'gmv' ? d.top_lojas_gmv : d.top_lojas_pedidos;
  document.getElementById('lojasBody').innerHTML = list.map((l,i)=>`
    <tr><td><span class="rank">${i+1}</span></td><td>${l.nome}</td><td><b>${fmtMoney(l.gmv)}</b></td><td>${l.pedidos}</td></tr>
  `).join('');
}"""

BLOCO_LOJAS_NOVO = """function renderLojas(){
  const d = dataStore.dias[daySelect.value];
  const list = (lojaMode === 'gmv' ? d.top_lojas_gmv : d.top_lojas_pedidos) || [];
  document.getElementById('lojasBody').innerHTML = list.map((l,i)=>`
    <tr><td><span class="rank">${i+1}</span></td><td>${l.nome}</td><td><b>${fmtMoney(l.gmv)}</b></td><td>${l.pedidos}</td></tr>
  `).join('');
}"""


def main():
    if not INDEX_HTML_PATH.exists():
        print(f"::error::{INDEX_HTML_PATH} não encontrado.")
        return
    texto = INDEX_HTML_PATH.read_text(encoding="utf-8")

    if BLOCO_ANTIGO not in texto:
        print("::warning::Bloco de renderDay (painel/cupons/ofertas) não encontrado como esperado — talvez já esteja corrigido. Pulando essa parte.")
    else:
        texto = texto.replace(BLOCO_ANTIGO, BLOCO_NOVO, 1)
        print("Corrigido: renderDay() agora trata painel/cupons_uso/cupons_categoria/ofertas_de_por ausentes sem quebrar.")

    if BLOCO_LOJAS_ANTIGO not in texto:
        print("::warning::Bloco de renderLojas não encontrado como esperado — talvez já esteja corrigido. Pulando essa parte.")
    else:
        texto = texto.replace(BLOCO_LOJAS_ANTIGO, BLOCO_LOJAS_NOVO, 1)
        print("Corrigido: renderLojas() agora trata top_lojas_gmv/pedidos ausentes sem quebrar.")

    INDEX_HTML_PATH.write_text(texto, encoding="utf-8")
    print(f"Gravado: {INDEX_HTML_PATH}")


if __name__ == "__main__":
    main()
