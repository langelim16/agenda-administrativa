---
name: horas-import
description: Importa as planilhas mensais de Horas de Funcionamento dos motores (1. leituras/3. horas-funcionamento/) para a aba HORAS MOTORES do artefato, gravando no Supabase. Usar quando o usuário pedir para ler/lançar/importar as horas dos motores ou conferir um novo mês.
---

# Importação mensal de Horas de Funcionamento (ODS → Supabase do artefato)

Mesmo modelo do pipeline de CLG (ver skill `clg-import`): extrair e gravar
direto, sem etapa de confirmação — a leitura tem se mostrado confiável.
Lançamentos são DADOS no Supabase.

**Permissão de escrita**: só incluir/atualizar lançamentos novos. Nunca
remover ou estornar nada direto — remoção é sempre **sugestão**, apresentada
ao usuário, mediante aprovação explícita antes de executar.

## Fonte

Planilhas ODS em `1. leituras/3. horas-funcionamento/` (subpastas por ano),
aba `CHN4`. Cada planilha traz o **acumulado** de horas por motor no fim do
mês. Extração: `python3 scripts/horas_extrair.py`.

- O mês de referência vem do **nome do arquivo** (`Ref-MAI2026`); o título
  interno às vezes está desatualizado (divergência é reportada em `avisos`).

## Regras

- **Identidade do motor**: navio (mapeado por padrão de nome → chave do
  artefato: nsampaio, castelo, tocantins, xingu, vega, denebola, regulus,
  boto) + Tipo do Motor (MCP/MCA/DGE) + Bordo. Nº de série serve de conferência.
- **Lançamento do mês = acumulado do mês − acumulado do mês anterior** (delta).
  A planilha mais antiga disponível é a **baseline**: não gera lançamento, só
  define/valida o acumulado inicial do motor no artefato.
- **Delta negativo é fisicamente impossível** (acumulado não diminui) — o
  extrator manda para a lista `revisar` em vez de propor lançamento; decidir
  com o usuário (linhas trocadas na planilha, digitação etc.).
- **Data do lançamento**: último dia do mês de referência.

## Gravação (formato do artefato — aba HORAS MOTORES)

Para cada lançamento aprovado, reproduzir o que o botão "+ Inserir horas em
operação" faz (funções horasSaveLanc/horasEstornarLanc no index.html):

- `aa_horas_<navio>_v1`: somar ao `horasOperacao` da linha do motor e
  recalcular `horasProxRevisao`/`horasUltrapassadas` (fórmula:
  `(horasManutencao + cronograma) − horasOperacao`);
- `aa_horas_readings_v1`: ponto `{t: último dia do mês, v: acumulado novo}`
  na chave = id da linha do motor; pontos posteriores somam o delta;
- `aa_audit_v1`: `Lançamento de horas: +<qtd> h (dd/mm/aaaa)[ · observação]`
  com scope `horas_<navio>` e rowId = id da linha (sintaxe parseada por
  horasParseLanc — manter compatível para Editar/Estornar funcionarem);
- bump `_meta` ao final.

Se houver lançamentos manuais duplicados do usuário para o mesmo mês/motor,
**não estornar direto** — listar como sugestão de estorno (motivo: duplicidade
com o lançamento do agente) e aguardar aprovação antes de marcar
`estornado`/reverter. O lançamento novo do agente pode ser incluído
normalmente mesmo com a sugestão pendente. Deltas negativos (`revisar`)
continuam exigindo decisão do usuário — isso não é validação de dado lido,
é ambiguidade real da planilha.

## Estado de processamento

Comparar contra o Supabase (o que já está lançado lá é a fonte de verdade) —
não manter lista de meses neste skill. O vigia automático
(`scripts/vigia_leituras.sh`) também registra o que já processou em
`.claude/leituras-estado.json`.

## Pendências de revisão conhecidas (registradas em jul/2026)

Tocantins MCP BE (FEV, −826), Sampaio MCA BE (MAI, −69,5) e Xingu (MCA/MCP
aparentemente trocados entre MAI/JUN, deltas de ±10.000) — deltas negativos
aguardando decisão do usuário.

## Notas operacionais

- Extensões `.ods`/`.ODS`/`.ODS.ods` são equivalentes (o extrator já trata);
  ignorar locks do LibreOffice (`~$*`).
- Ao gravar, atualizar também `aa_lastedit_v1` (chave `horas_<navio>`) com
  timestamp atual, junto do bump `_meta` — é o que faz o app mostrar
  "Última edição em…" na tabela.
- Pasta nova em `1. leituras/` = criar novo skill + mapeamento em
  `scripts/vigia_leituras.sh` + entrada WatchPaths no plist
  `~/Library/LaunchAgents/com.lucasangelim.agenda-leituras.plist` + reload.
