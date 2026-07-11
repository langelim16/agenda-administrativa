---
name: pmpe-import
description: Importa as comissões (em andamento/previstas) dos PMPE em PDF para a tabela Comissões da aba CONDEF do artefato, gravando no Supabase. Usar quando o usuário pedir para ler/lançar/importar o PMPE ou atualizar a tabela Comissões do CONDEF.
---

# Importação de Comissões do PMPE (PDF → tabela Comissões do CONDEF)

Mesmo modelo do pipeline de CLG (ver skill `clg-import`): extrair → conferir
com o usuário → só gravar após autorização. Lançamentos são DADOS no
Supabase, nunca alterações no código.

Processo **independente** do `clg-import`: ambos leem os mesmos PDFs do
PMPE, mas o `clg-import` só usa o período de comissão como insumo pra cruzar
com consumo de CLG. Aqui o objetivo final é outro — popular a tabela
**Comissões** da aba CONDEF (`aa_navios_comissoes_v1`). Não duplicar lógica
de parsing de PDF entre os dois: os dois usam `scripts/pmpe_extrair.py`.

## Fonte

PMPE em PDF em `1. leituras/2. pmpe/AAAA/PMPE MES-AAAA PARTE I.pdf`.
Extração: `python3 scripts/pmpe_extrair.py "1. leituras/2. pmpe"` (JSON no
stdout, avisos de parsing no stderr). Cada evento extraído já vem filtrado
para os 8 meios do CHN-4 e traz: `nEvt`, `tipo` (PMPE/ADM), `meio`,
`dataInicio`, `dataFim`, `duracaoDias`, `area`, `operacao`, `proposito`.

## Regras de mapeamento

- **Escopo**: mesmos 8 meios do CHN-4 usados no `clg-import` (NHo Garnier
  Sampaio, NHiB Tenente Castelo, AvHoFlu Rio Tocantins, AvHoFlu Rio Xingu,
  AvB Vega, AvB Denebola, AvB Regulus, AvB Boto) — o extrator já filtra isso.
- **Colunas da tabela Comissões** (`aa_navios_comissoes_v1`, colunas em
  `aa_navios_comissao_cols_v1`): `meio`, `comissao`, `inicio` (date), `fim`
  (date), `localizacao`, `clg` (CLG Autorizado), `pmpe`. Mapeamento sugerido:
  - `meio` ← `meio`
  - `comissao` ← `nEvt` + `proposito`/`operacao` (texto descritivo curto,
    usar julgamento — ver exemplos já lançados na tabela antes de propor)
  - `inicio`/`fim` ← `dataInicio`/`dataFim`
  - `localizacao` ← `area`
  - `pmpe` ← `nEvt` (nº do evento PMPE, formato `NN.NN`)
  - `clg`: não vem do PMPE — deixar em branco ou perguntar ao usuário se
    houver dado de CLG autorizado disponível
- **Tipo PMPE vs ADM**: eventos `ADM` são administrativos, não comissão
  operativa propriamente dita — confirmar com o usuário se devem entrar na
  tabela Comissões (padrão: só lançar `PMPE`, salvo indicação em contrário).
- **Sem status explícito de "em andamento"/"prevista"** na tabela — não há
  coluna de situação; a UI decide isso pela data corrente vs `inicio`/`fim`.
  Não inventar coluna nova.
- **Duplicatas/atualizações**: se um evento (`meio` + `pmpe`/`nEvt`) já
  lançado na tabela aparecer de novo num PMPE mais recente com dados
  diferentes (datas retificadas, área alterada etc.), o PMPE mais recente é
  a fonte de verdade — mas **decidir com o usuário** antes de sobrescrever
  se houver qualquer dúvida (ex.: divergência grande de datas, comissão já
  marcada como concluída manualmente).

## Fluxo de execução

1. Rodar `scripts/pmpe_extrair.py` na pasta do PMPE.
2. Cruzar com o conteúdo atual de `aa_navios_comissoes_v1` (ler via Supabase
   ou pedir ao usuário) para identificar o que já está lançado.
3. **Apresentar tabela de conferência ao usuário e aguardar autorização** —
   nunca gravar sem o "pode lançar".
4. Gravar no Supabase no formato da tabela Comissões:
   - `aa_navios_comissoes_v1`: adicionar/atualizar linhas
     `{id:genUid("cms"), meio, comissao, inicio, fim, localizacao, clg, pmpe}`;
   - se uma linha existente for atualizada (retificação), preservar o `id`;
   - bump da chave `_meta` ao final para os dispositivos sincronizarem.
