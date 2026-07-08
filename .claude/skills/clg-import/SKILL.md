---
name: clg-import
description: Importa os lançamentos mensais de consumo/abastecimento de CLG das planilhas ODS (pasta CLG/) e dos PMPE em PDF (períodos de comissão) para o artefato, gravando no Supabase. Usar quando o usuário pedir para ler/lançar/importar as planilhas de CLG ou conferir um novo mês.
---

# Importação mensal de CLG (planilhas ODS → Supabase do artefato)

Processo definido com o usuário em 08/07/2026. Os lançamentos são DADOS no
Supabase (mesmas chaves que o artefato usa), nunca alterações no código.

## Fontes

1. **Planilhas ODS** em `1. leituras/1. clg/` — uma por mês (aba `Consumos` + aba `Estoques Físicos`).
   Extração: `python3 scripts/clg_extrair.py "1. leituras/1. clg"` (JSON pronto para conferência).
2. **PMPE em PDF** em `1. leituras/2. pmpe/` — contém os **períodos de comissão** de cada
   navio. É de lá que saem os **dias de comissão** dos consumos operativos
   (a planilha não traz esse dado).
   (Há também `1. leituras/3. horas-funcionamento/` para os controles de horas de motores.)
   Obs.: o usuário renomeia pastas às vezes — se um caminho não existir, procurar
   pelo conteúdo em vez de falhar.

## Regras de mapeamento

- **Escopo**: somente os navios subordinados ao CHN-4 (NHo Garnier Sampaio,
  NHiB Tenente Castelo, AvHoFlu Rio Tocantins, AvHoFlu Rio Xingu, AvB Vega,
  AvB Denebola, AvB Regulus, AvB Boto). **Desconsiderar** Viaturas, Farol de
  Salinópolis e CHN-4 (sede), e os produtos QAV/ODR/Álcool.
- **Produtos**: ODM (Tipo 04M) → tabela Estoque de ODM (`aa_clg_t1_v1`);
  Gasolina (Tipo 01), LUB (Tipo 06), GRAXA (Tipo 08) → tabela
  Gasolina/Lubrificantes/Graxas (`aa_clg_t3nav_v1`/`aa_clg_t3emb_v1`).
- **Tipo**: REF EVT `PMPE` → consumo **Operativo** (Nº Evento PMPE = coluna
  `Nº EVT`, Descrição = `DESCRIÇÃO DO EVENTO`); `ADM` → **Administrativo**
  (descrição vira justificativa, se houver algo além de "ADMINISTRATIVO").
- **Data do lançamento**: sempre o **último dia do mês de referência** da
  planilha (é quando o usuário a recebe). Ex.: JAN → 31/01.
- **Dias de comissão** (consumos operativos): extrair do período do evento no
  PMPE em PDF correspondente ao Nº do evento. Sem o PDF, perguntar ao usuário.

## Abastecimentos implícitos (regra do saldo)

As planilhas não discriminam abastecimentos. Inferir por diferença de saldo:

```
saldo_calculado = estoque_inicial_do_mês − Σ consumos do mês (por meio/produto)
abastecimento  = estoque_físico_fim_do_mês (aba Estoques Físicos) − saldo_calculado
```

Se `abastecimento > 0`, lançar um **abastecimento** desse valor com data no
**dia 01 do mês seguinte**. Exemplo validado: Tocantins jan/2026 — início
22.268, consumo 10.766 → 11.502; estoque físico 21.502 → abastecimento de
10.000 lançado em 01/02.

## Fluxo de execução

1. Rodar o extrator e cruzar com os PMPE (dias de comissão).
2. **Apresentar tabela de conferência ao usuário e aguardar autorização** —
   nunca gravar sem o "pode lançar".
3. Antes de lançar, **remover lançamentos manuais duplicados** do usuário para
   o mesmo mês/meio (marcar `estornado` na auditoria e reverter efeito),
   substituindo-os pelos lançamentos do agente.
4. Gravar no Supabase com o MESMO formato do artefato:
   - estoque: atualizar célula do meio em `aa_clg_t1_v1` (ODM) ou t3 (GLG);
   - histórico do gráfico `aa_clg_estoque_hist_v1`: consumo = pontos diários
     distribuídos no período (chave = id da linha; GLG usa `id_produto`),
     abastecimento = 1 ponto na data; manter ponto de "hoje" = estoque atual;
   - auditoria `aa_audit_v1`: mesma sintaxe dos lançamentos do app, ex.:
     `Consumo retroativo (operativo): -10766 em 20 dia(s) (31/01/2026) · PMPE 01.11 · RIO AMAZONAS X`
     `Abastecimento retroativo: +10000 (01/02/2026)`
     (essa sintaxe é parseada por `clgParseLanc` no index.html — manter compatível);
   - bump da chave `_meta` ao final para os dispositivos sincronizarem.
5. Estado em jul/2026: JAN–MAR e MAI extraídos; ABR e JUN chegam depois.
