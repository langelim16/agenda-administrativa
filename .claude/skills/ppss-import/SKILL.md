---
name: ppss-import
description: Importa os Pedidos de Serviço dos Meios (PPSS, Correntes + Programadas) das planilhas ODS (1. leituras/4. ppss/) para a aba PPSS do artefato, gravando no Supabase. Usar quando o usuário pedir para ler/lançar/importar as planilhas de PPSS ou conferir uma nova leitura mensal.
---

# Importação mensal de PPSS (planilhas ODS → Supabase do artefato)

Processo definido com o usuário em 14/07/2026. Diferente do CLG (que acumula
lançamentos), aqui cada leitura **substitui** os dados existentes — a
planilha é a fonte de verdade completa do estado atual dos pedidos, não um
incremento.

**Permissão de escrita**: a cada leitura, o skill sincroniza `aa_ppss_v1`
para espelhar exatamente o que está nas duas planilhas (upsert por
`navio`+`numero`, chaves protegidas `PPSS_FIXED_KEYS` no app). Pedidos que
sumiram da planilha (encerrados/removidos pelo usuário) — apresentar como
**sugestão de remoção**, mediante aprovação explícita, igual à regra de
estorno do CLG. Nunca remover direto.

## Fontes

Duas planilhas em `1. leituras/4. ppss/`, cada uma com 4 abas (uma por
navio: `NHoGSampaio`, `NHiBTenCastelo`, `AvHoFluRioTocantins`,
`AvHoFluRioXingu` — mesmos nomes usados no app):

1. Arquivo com `CORRENTE` no nome → pedidos de **Manutenção Corrente**.
2. Arquivo com `PROGRAMADA` no nome → pedidos de **Manutenção Programada**.

Formato: `.ods` OU `.xlsx` (o usuário passou a mandar a PROGRAMADAS em
xlsx em 15/07/2026; o extrator lê os dois). No xlsx o layout de colunas
**varia por aba** — o extrator resolve pelas linhas de cabeçalho 8 (grupos
mesclados: IDENTIFICAÇÃO/Orçamento/Aditamento/REC IND/FALTA INDICAR/MSG/
SITUAÇÃO/ALTCRED P/ BNVC) e 9 (sub-colunas), nunca por índice fixo.

Extração: `python3 scripts/ppss_extrair.py "1. leituras/4. ppss"` (JSON
pronto para conferência).

Obs.: o usuário renomeia pastas às vezes — se o caminho não existir,
procurar pelo conteúdo em vez de falhar.

## Regras de mapeamento

- **Situação: o TEXTO da coluna SITUAÇÃO é a fonte primária** (TERMINADO→
  Concluído, CANCELADO, FALTA INDICAR, RECURSO INDICADO, ORÇADO E NÃO
  INDICADO, NÃO ORÇADO). A **cor de fundo da linha é fallback** quando a
  coluna está vazia (regra corrigida em 15/07/2026 — a cor sozinha deixava
  a maioria sem situação). Mapeamento de cores:
  - `#33cccc` → `Concluído`
  - `#ff0000` → `Cancelado`
  - `#dc85e9` → `Falta Indicar`
  - `#2cee0e` → `Recurso Indicado`
  - `#ffcc99` → `Orçado e não Indicado`
  - `#536dfe` → `Não orçado`
  - Cor não mapeada (`transparent` ou outra) → `situacao` fica vazia; não
    inventar categoria, deixar em branco (linha ainda sem status definido
    na própria planilha).
- **Tipo**: nome do arquivo contém `CORRENTE` → `Corrente`; contém
  `PROGRAMADA` → `Programada`.
- **Colunas a ler na planilha e para onde vão** (definido com o usuário em
  14/07/2026; schema `PPSS_FIXED` no index.html):
  - `NAVIO` → aba (nome já é o `navio`).
  - `N°` → `numero`.
  - `Descrição` → `descricao`.
  - `DS` → `ds`.
  - `Orçamento + Aditamento` → `orcamento` + `aditamentos` (ler as duas
    colunas separadas, não somar antes de gravar).
  - `REC IND` (Recurso Indicado) → `recInd` (coluna própria no schema
    desde 15/07/2026). **Recurso Indicado Integral**: quando a situação é
    `RECURSO INDICADO`/`INDICADO RECURSO INTEGRAL` e a célula REC IND vem
    vazia (preenchedor só marcou a situação, não repetiu o valor), `recInd`
    = `orcamento` (indicado integral = o próprio orçado). Aplicado no
    extrator (`ppss_extrair.py`, `extrair_arquivo`/`extrair_xlsx`) e como
    fallback de leitura no app (`ppssRecIndVal`, cobre registros antigos já
    gravados sem o fallback). Bug real: 6 pedidos "Recurso Indicado" com
    `recInd` vazio sumiam do KPI "Valor indicado" (AvHoFluRioTocantins
    #0001/#0002/2007/2014, NHoGSampaio #0004/#0018 — achado pelo usuário em
    15/07/2026).
  - `ALTCRED P/ BNVC` → `altcredBnvc` (coluna própria desde 15/07/2026).
  - `FALTA INDICAR` (fórmula = Orçamento − REC IND, já calculada na
    planilha) → `faltaIndicar`.
  - `MSG` → **não vai para uma coluna única**; cada mensagem tem um
    DATAHORA — incluir cada uma separadamente no resumo do PPSS (painel
    lateral direito do app), listada por data/hora. Gravar em `msgOmps`
    (mensagens da OMPS) e `msgNav` (mensagens do Navio) conforme a origem
    indicada na planilha, preservando o texto com data/hora de cada
    lançamento (não sobrescrever o que o usuário já tiver preenchido
    manualmente — só anexar o que for novo).
  - `OMPS ORÇ` (Orçamento da OMPS), `NAV - SOL IND REC` (Navio solicitando
    Indicação de Recurso), `COMIMSUP - IND REC` (Indicação de Recurso pelo
    COMIMSUP), `OMPS - TÉRMINO` (término do serviço pela OMPS),
    `SATISFEITO/CANCELADO` (pelo Navio) → sem coluna própria no schema
    ainda; tratar como contexto para o resumo lateral (mesmo tratamento de
    `MSG`, com datas quando houver) até o usuário definir campos formais.
  - `SITUAÇÃO` → `situacao`, vem da **cor de fundo da linha** (mesma dos 6
    KPI coloridos exibidos abaixo dos KPI Programas/Correntes no app — as
    cores e nomes já batem 1:1 com o mapeamento de `COR_SITUACAO` abaixo).
- **Fim da tabela**: a linha `SUBTOTAL` fecha a tabela de pedidos — o
  extrator **para** ao encontrá-la, não pula linhas depois dela. Abaixo do
  SUBTOTAL a planilha às vezes tem células soltas (mini-tabela STATUS/% de
  PPSS ENC, SALDO/DÍVIDA por navio, SALDO REMANESCENTE BNVC) — são
  anotações da planilha, não pedidos, e nunca devem virar linha no artefato
  mesmo que caiam sobre alguma coluna da tabela (caso real removido em
  14/07/2026, aba NHoGSampaio da planilha CORRENTE — 15 pedidos fantasma
  entraram no Supabase antes dessa blindagem).

## Fluxo de execução

1. Rodar o extrator e conferir a saída (contagem por navio/tipo/situação)
   contra uma leitura manual rápida das planilhas.
2. Buscar o estado atual de `aa_ppss_v1` no Supabase.
3. Para cada pedido do extrator: upsert por `navio`+`numero` (atualiza se já
   existe, insere se novo). **Preservar campos manuais do app não presentes
   na planilha** (ex.: `msgOmps`, `msgNav` se o usuário já os preencheu
   manualmente) — só sobrescrever os campos que a planilha de fato traz.
4. Pedidos que existem em `aa_ppss_v1` mas não apareceram na extração atual
   (removidos da planilha) → listar como sugestão de remoção, aguardar
   aprovação antes de excluir.
5. Gravar `aa_ppss_v1` atualizado no Supabase, sem etapa de confirmação
   para a leitura em si (mesma lógica do clg-import — a leitura das
   planilhas tem se mostrado confiável); a sugestão de remoção do passo 4
   continua exigindo aprovação.
6. Bump de `_meta` e de `aa_lastedit_v1` (chave `ppss_tbl`) com timestamp
   atual, para os dispositivos sincronizarem e o app mostrar "Última edição
   em…".
7. Auditoria (`aa_audit_v1`): um registro por pedido novo/atualizado, ex.:
   `PPSS importado: NHiBTenCastelo #0001 · Orçado e não Indicado (R$ 18.008,54)`.

## Notas operacionais

- Extensões `.ods`/`.ODS` equivalentes; ignorar locks do LibreOffice (`~$*`).
- Pasta nova em `1. leituras/` = criar novo skill + mapeamento em
  `scripts/vigia_leituras.sh` + entrada WatchPaths no plist
  `~/Library/LaunchAgents/com.lucasangelim.agenda-leituras.plist` + reload.
