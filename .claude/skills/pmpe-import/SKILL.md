---
name: pmpe-import
description: Importa as comissões em andamento/previstas (nunca passadas) dos PMPE em PDF para a tabela Comissões da aba CONDEF do artefato, gravando no Supabase. Usar quando o usuário pedir para ler/lançar/importar o PMPE ou atualizar a tabela Comissões do CONDEF.
---

# Importação de Comissões do PMPE (PDF → tabela Comissões do CONDEF)

Processo **independente** do `clg-import`: ambos leem os mesmos PDFs do
PMPE, mas o `clg-import` usa o período de comissão como insumo pra cruzar
com consumo de CLG (inclusive de meses passados). Aqui o objetivo é outro —
manter a tabela **Comissões** da aba CONDEF (`aa_navios_comissoes_v1`)
com o que está em andamento ou previsto. Não duplicar lógica de parsing de
PDF entre os dois: os dois usam `scripts/pmpe_extrair.py`.

Sem etapa de confirmação — a leitura do PMPE já se mostrou confiável.
Extrai e grava direto no Supabase.

**Permissão de escrita**: só incluir comissões novas e atualizar campos de
comissões já lançadas (ver "Duplicatas/atualizações" abaixo). Nunca remover
uma linha da tabela direto — se uma comissão lançada não aparecer mais no
PMPE mais recente (cancelada, incorporada a outro evento etc.), isso é
**sugestão** de remoção apresentada ao usuário, mediante aprovação explícita
antes de excluir.

## Fonte

PMPE em PDF em `1. leituras/2. pmpe/AAAA/PMPE MES-AAAA PARTE I.pdf` — usar
sempre o **PDF mais recente disponível** (é a fonte de verdade; PMPEs de
meses anteriores só interessam ao `clg-import`, não a este skill).
Extração: `python3 scripts/pmpe_extrair.py "1. leituras/2. pmpe" --desde AAAA-MM-DD`
(data de hoje — descarta comissões já encerradas; JSON no stdout, avisos de
parsing no stderr).

**Atenção**: o parser tropeça em páginas com dois eventos lado a lado
(colunas), podendo trocar campos de período/propósito entre eventos
vizinhos. Ler o PDF diretamente (`extract_text`) pra conferir os campos de
cada evento CHN-4 antes de gravar — não copiar o JSON do script sem olhar
o texto bruto do evento correspondente.

## Filtro: só presente e futuro

**Nunca lançar comissão já encerrada** (data fim < hoje). Ao extrair,
descartar todo evento com `dataFim` no passado — só interessam comissões em
andamento ou previstas.

## Schema real da tabela (`aa_navios_comissoes_v1`)

Lida via REST do Supabase: `agenda_data(key,value,updated_at)`, linha
`key=aa_navios_comissoes_v1`, `value` = JSON array de objetos:

```json
{"id": "cms_pmpeNN_NN", "meio": "NHoGSampaio", "pmpe": "07.15",
 "comissao": "ADECOM H37", "status": "Em andamento",
 "inicio": "08/07/2026", "fim": "15/07/2026",
 "localizacao": "Rio Pará, Região dos Estreitos e Rio Amazonas-PA",
 "clg": "ODM: 22.100L\nOL: 900L\nGAS: 50L",
 "manualFields": []}
```

Linhas antigas sem `manualFields` são tratadas como `[]` (nada travado).

- **`meio`**: chave curta, não o nome completo do artefato. Mapeamento:
  NHo Garnier Sampaio → `NHoGSampaio`; NHiB Tenente Castelo →
  `NHiBTenCastelo`; AvHoFlu Rio Tocantins → `AvHoFluRioTocantins`;
  AvHoFlu Rio Xingu → `AvHoFluRioXingu`; AvB Vega → `AvBVega`; AvB Denebola
  → `AvBDenebola`; AvB Regulus → `AvBRegulus`; AvB Boto → `AvBBoto`
  (conferir contra chaves já usadas na tabela antes de inventar uma nova).
- **`pmpe`**: nº do evento (`NN.NN`).
- **`comissao`**: nome da operação/exercício (campo "OPERAÇÕES/EXERCÍCIO"
  do PDF), não o propósito.
- **`status`**: `"Em andamento"` (hoje ∈ [início, fim]), `"Prevista"` (hoje
  < início), ou `"Concluída"` (hoje > fim — mas essas não devem ser
  lançadas por este skill, ver filtro acima). Status como `"A ser adiada"`
  é **decisão operacional manual** do usuário, nunca inferir/sobrescrever
  automaticamente a partir de datas.
- **`inicio`/`fim`**: string `DD/MM/AAAA` (não ISO).
- **`localizacao`**: campo "ÁREA/PORTO" do PDF.
- **`clg`**: texto multi-linha do consumo autorizado (campo "Consumo:" das
  observações), formato `"PRODUTO: valorL\n..."` — um produto por linha.
- **`id`**: `cms_pmpe` + nº do evento sem ponto, ex. `07.15` → `cms_pmpe07_15`
  (conferir padrão contra ids já existentes na tabela).
- **`manualFields`**: array de nomes de campo (`status`, `inicio`, `fim`,
  `localizacao`, `clg`, `comissao`, `meio`, `pmpe`) que o usuário editou
  manualmente pela tabela do app. Presença nesse array é **hierarquicamente
  superior** a qualquer dado do PMPE — ver "Duplicatas/atualizações".

## Escopo

Mesmos 8 meios do CHN-4 usados no `clg-import` (NHo Garnier Sampaio, NHiB
Tenente Castelo, AvHoFlu Rio Tocantins, AvHoFlu Rio Xingu, AvB Vega, AvB
Denebola, AvB Regulus, AvB Boto) — o extrator já filtra isso. Eventos `ADM`
não são comissão operativa — só lançar `PMPE`.

## Duplicatas/atualizações

Se um evento (`meio` + `pmpe`) já lançado aparecer de novo no PDF mais
recente com dados diferentes (datas retificadas, área alterada), o PDF mais
recente é a fonte de verdade para os campos que o usuário **nunca** editou
manualmente pelo app — atualizar a linha existente preservando o `id`.

**Regra hierárquica de `manualFields`**: antes de sobrescrever qualquer campo
de uma linha existente, checar `row.manualFields` (array de nomes de campo).
Se a chave do campo está em `manualFields`, **nunca sobrescrever** —
preservar o valor atual mesmo que o PDF traga algo diferente, sem exceção e
sem perguntar. A leitura do PMPE é puramente cadastral: só grava campos que o
usuário nunca tocou. Editar de volta um campo travado é decisão exclusiva do
usuário pela tabela do app — não há downgrade automático de `manualFields`
por este skill. Isso vale para todos os campos, não só `status`.

## Fluxo de execução

1. Rodar `scripts/pmpe_extrair.py` no PDF mais recente e conferir cada
   evento CHN-4 contra o texto bruto do PDF (ver aviso acima sobre colunas).
2. Descartar comissões já encerradas (fim < hoje).
3. Ler `aa_navios_comissoes_v1` atual via REST do Supabase.
4. Gravar direto — adicionar linhas novas, atualizar as existentes
   (preservando `id` e nunca sobrescrevendo campos em `manualFields`, ver
   acima). Se alguma linha existente não corresponder a nenhum evento do
   PMPE mais recente, NÃO remover — listar como sugestão de remoção e
   aguardar aprovação.
5. Atualizar `aa_lastedit_v1` (chave `nv_comissao`) com timestamp atual —
   é o que faz o app mostrar "Última edição em…" na tabela Comissões.
6. Bump da chave `_meta` ao final para os dispositivos sincronizarem.

## Notas operacionais

- Ignorar locks (`~$*`) e tratar extensões case-insensitive.
- Pasta nova em `1. leituras/` = criar novo skill + mapeamento em
  `scripts/vigia_leituras.sh` + entrada WatchPaths no plist
  `~/Library/LaunchAgents/com.lucasangelim.agenda-leituras.plist` + reload.
