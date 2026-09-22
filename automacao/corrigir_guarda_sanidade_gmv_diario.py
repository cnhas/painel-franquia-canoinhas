"""
Script de correcao pontual (rodar 1x): adiciona uma trava de sanidade em
ler_gmv_meta_dia_unico(), pra NUNCA MAIS deixar um valor diario implausivel
ser silenciosamente gravado em gmv_diario_mes.

Contexto (22/09/2026): o backfill automatico via
preencher_dias_faltantes_gmv_diario() funcionou perfeitamente pra Julho e
Agosto (meses ja fechados - valores diarios plausiveis, ~R$8mil-23mil/dia),
mas pra Setembro (mes CORRENTE, ainda em andamento) os valores lidos via
filtro de "dia unico" vieram claramente errados: crescentes e enormes
(R$464mil no dia 1 ate R$762mil no dia 21) - maiores ate que o total do
mes inteiro. A causa raiz exata (por que o filtro de dia unico se comporta
diferente pra datas do mes corrente vs meses ja fechados) ainda NAO foi
identificada - precisa de mais investigacao com acesso interativo ao site
real do Data Much.

Enquanto isso, esta trava impede que o bug volte a corromper dados
silenciosamente: se o GMV ou a Meta lidos pra um unico dia vierem acima de
um teto generoso (bem maior que qualquer dia real ja visto), a funcao
levanta RuntimeError em vez de aceitar o valor. Isso faz o workflow
"Atualizar Data Much" falhar ALTO (com screenshot de diagnostico, via
_diagnosticar_erro) em vez de gravar um numero errado - e como a excecao
acontece ANTES de atualizar_arquivos() ser chamado, NENHUM arquivo e
sobrescrito nessa execucao, entao os dados corretos que ja existem
continuam intactos. Preferimos o painel INCOMPLETO (faltando alguns dias)
a MOSTRAR um numero errado - conforme a diretriz do usuario.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "automacao" / "scrape_datamuch.py"

# Teto generoso: bem acima do maior dia real ja observado (~R$23mil), mas bem
# abaixo dos valores corrompidos vistos (R$464mil-762mil) - qualquer dia real
# de GMV ou Meta acima disso e quase certamente um sinal de leitura errada
# (ex: card mostrando acumulado do mes/ano em vez do dia isolado).
TETO_SANIDADE = 100_000

TRECHO_ANTIGO = '''def ler_gmv_meta_dia_unico(frame):
    """Le os cards GMV (Realizado) e Meta do report/208 ja filtrado pra um unico
    dia. Retorna (gmv, meta). Mesma funcao ja usada e validada em
    scrape_dia_datamuch.py."""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_gmv = re.search(r"\\bGMV\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Realizado", texto)
        m_meta = re.search(r"\\bMeta\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Meta\\b", texto)
        if m_gmv and m_meta:
            return round(parse_valor_brl(m_gmv.group(1)), 2), round(parse_valor_brl(m_meta.group(1)), 2)
        if time.monotonic() >= limite:
            raise RuntimeError(f"Nao achei os cards GMV/Meta (dia unico). Texto: {texto[:1500]!r}")
        _esperar(frame, 500)'''

TRECHO_NOVO = f'''def ler_gmv_meta_dia_unico(frame):
    """Le os cards GMV (Realizado) e Meta do report/208 ja filtrado pra um unico
    dia. Retorna (gmv, meta). Mesma funcao ja usada e validada em
    scrape_dia_datamuch.py.

    TRAVA DE SANIDADE (adicionada em 22/09/2026): descobrimos que pra datas
    dentro do MES CORRENTE (ainda em andamento), o filtro de dia unico as
    vezes retorna valores muito maiores que um dia real (parece cair pra
    algum tipo de acumulado em vez do dia isolado - causa raiz exata ainda
    nao identificada). Em vez de aceitar cegamente, rejeita valores acima de
    um teto bem folgado - bem maior que qualquer dia real ja visto, mas bem
    menor que os valores corrompidos observados (R$464mil-762mil). Se
    acontecer, levanta erro (falha alta, sem gravar nada errado) em vez de
    corromper gmv_diario_mes silenciosamente.
    (teto atual: R$ {TETO_SANIDADE:,})"""
    corpo = frame.locator("body")
    limite = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while True:
        texto = corpo.inner_text()
        m_gmv = re.search(r"\\bGMV\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Realizado", texto)
        m_meta = re.search(r"\\bMeta\\b\\s*\\n?\\s*R\\$\\s?([\\d.,]+)\\s*\\n?\\s*Meta\\b", texto)
        if m_gmv and m_meta:
            gmv_dia = round(parse_valor_brl(m_gmv.group(1)), 2)
            meta_dia = round(parse_valor_brl(m_meta.group(1)), 2)
            if gmv_dia > TETO_SANIDADE or meta_dia > TETO_SANIDADE:
                raise RuntimeError(
                    f"Valor de dia unico implausivel (gmv={{gmv_dia}} meta={{meta_dia}}, "
                    f"teto={{TETO_SANIDADE}}) - provavelmente o filtro de dia unico nao "
                    f"isolou corretamente esse dia (bug conhecido pra datas do mes "
                    f"corrente, causa raiz ainda em investigacao). Abortando pra nao "
                    f"gravar dado errado. Texto: {{texto[:1500]!r}}"
                )
            return gmv_dia, meta_dia
        if time.monotonic() >= limite:
            raise RuntimeError(f"Nao achei os cards GMV/Meta (dia unico). Texto: {{texto[:1500]!r}}")
        _esperar(frame, 500)'''


def main():
    if not SCRIPT_PATH.exists():
        print(f"::error::{SCRIPT_PATH} nao encontrado.")
        return
    texto = SCRIPT_PATH.read_text(encoding="utf-8")

    if "TETO_SANIDADE" in texto:
        print("Ja tem TETO_SANIDADE - talvez ja corrigido. Pulando.")
        return

    if TRECHO_ANTIGO not in texto:
        print("::error::Trecho antigo de ler_gmv_meta_dia_unico nao encontrado - talvez ja mudou.")
        return

    ANCORA_CONSTANTE = "NAV_TIMEOUT_MS = 45000"
    if ANCORA_CONSTANTE not in texto:
        print(f"::error::Ancora de constante {ANCORA_CONSTANTE!r} nao encontrada.")
        return

    declaracao_teto = (
        "\n\n# Teto generoso pra trava de sanidade de ler_gmv_meta_dia_unico: bem acima\n"
        "# do maior dia real ja observado (~R$23mil), mas bem abaixo dos valores\n"
        "# corrompidos vistos em dias do mes corrente (R$464mil-762mil).\n"
        f"TETO_SANIDADE = {TETO_SANIDADE}"
    )
    texto_novo = texto.replace(ANCORA_CONSTANTE, ANCORA_CONSTANTE + declaracao_teto, 1)
    texto_novo = texto_novo.replace(TRECHO_ANTIGO, TRECHO_NOVO, 1)
    SCRIPT_PATH.write_text(texto_novo, encoding="utf-8")
    print(f"Gravado {SCRIPT_PATH} - trava de sanidade adicionada em ler_gmv_meta_dia_unico (teto=R$ {TETO_SANIDADE:,}).")


if __name__ == "__main__":
    main()
