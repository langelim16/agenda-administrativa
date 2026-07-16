#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator dos Pedidos de Serviço dos Meios (PPSS) das planilhas ODS
(pasta "1. leituras/4. ppss/").

Uso: python3 scripts/ppss_extrair.py [pasta]   (padrão: "1. leituras/4. ppss")
Saída: JSON com um pedido por linha, pronto para conferência e posterior
substituição de aa_ppss_v1 no Supabase do artefato.

Layout real das colunas (linhas 8/9 do cabeçalho, spans resolvidos —
conferido em 15/07/2026):
  0 NAVIO | 1 N° | 2 DESCRIÇÃO | 3 OMPS | 4 DS
  5 Orçamento FR-170 | 6 Aditamento FR-171 | 7 ADT 01
  8-9 REC IND | 10 FALTA INDICAR | 11 ALT ESCOPO
  12 MSG OMPS–ORÇ | 13 MSG NAV–SOL IND REC | 14 MSG COMINSUP–IND REC
  15 MSG OMPS-TÉRMINO | 16 MSG SATISFEITO/CANCELADO
  17 SITUAÇÃO (texto) | 18 ALTCRED P/ BNVC | 19 OBSERVAÇÕES

- SITUAÇÃO: fonte primária é o TEXTO da col 17; fallback é a cor de fundo
  da linha (legenda B2:B7). Mapeamentos abaixo.
- Substituição total: cada leitura é o espelho do que está nas planilhas
  (upsert por navio+numero) — não acúmulo como no CLG.
"""
import zipfile, xml.etree.ElementTree as ET, glob, json, sys, os

NS = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
      'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
      's': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
      'fo': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'}

COR_SITUACAO = {
    '#33cccc': 'Concluído',
    '#ff0000': 'Cancelado',
    '#dc85e9': 'Falta Indicar',
    '#2cee0e': 'Recurso Indicado',
    '#ffcc99': 'Orçado e não Indicado',
    '#536dfe': 'Não orçado',
}
TEXTO_SITUACAO = {
    'TERMINADO': 'Concluído',
    'CONCLUÍDO': 'Concluído',
    'CANCELADO': 'Cancelado',
    'FALTA INDICAR': 'Falta Indicar',
    'RECURSO INDICADO': 'Recurso Indicado',
    'ORÇADO E NÃO INDICADO': 'Orçado e não Indicado',
    'NÃO ORÇADO': 'Não orçado',
}
NAVIOS = ['NHoGSampaio', 'NHiBTenCastelo', 'AvHoFluRioTocantins', 'AvHoFluRioXingu']

# (índice de coluna, rótulo) das 5 colunas de MSG e destino msgOmps/msgNav
MSG_COLS = [
    (12, 'OMPS ORÇ', 'msgOmps'),
    (13, 'NAV – SOL IND REC', 'msgNav'),
    (14, 'COMINSUP – IND REC', 'msgNav'),
    (15, 'OMPS-TÉRMINO', 'msgOmps'),
    (16, 'SATISFEITO/CANCELADO', 'msgNav'),
]


def cell_styles_bg(root):
    """Mapa style-name -> cor de fundo (fo:background-color), só estilos de célula."""
    out = {}
    for st in root.iter('{%s}style' % NS['s']):
        if st.get('{%s}family' % NS['s']) != 'table-cell':
            continue
        name = st.get('{%s}name' % NS['s'])
        for props in st.iter('{%s}table-cell-properties' % NS['s']):
            bg = props.get('{%s}background-color' % NS['fo'])
            if bg:
                out[name] = bg.lower()
    return out


def sheet_rows(root, sheetname, styles):
    for tb in root.iter('{%s}table' % NS['t']):
        if tb.get('{%s}name' % NS['t']) != sheetname:
            continue
        rows = []
        for tr in tb.iter('{%s}table-row' % NS['t']):
            rep_row = int(tr.get('{%s}number-rows-repeated' % NS['t']) or 1)
            cells = []
            for tc in tr:
                # inclui covered-table-cell (células sob span) p/ manter alinhamento
                if not tc.tag.endswith('table-cell'):
                    continue
                rep = int(tc.get('{%s}number-columns-repeated' % NS['t']) or 1)
                txt = ' '.join(''.join(p.itertext())
                               for p in tc.iter('{%s}p' % NS['x']))
                bg = styles.get(tc.get('{%s}style-name' % NS['t']))
                cells += [(txt, bg)] * min(rep, 25)
            if rep_row > 1 and not any(c[0] for c in cells):
                continue
            rows.append(cells)
        return rows
    return []


def _txt(r, i):
    return r[i][0].strip() if len(r) > i else ''


def extrair_arquivo(f, tipo):
    root = ET.fromstring(zipfile.ZipFile(f).read('content.xml'))
    styles = cell_styles_bg(root)
    pedidos = []
    for navio in NAVIOS:
        rows = sheet_rows(root, navio, styles)
        if not rows:
            continue
        for r in rows[9:]:
            navio_cell = _txt(r, 0)
            numero = _txt(r, 1)
            if not numero or numero.upper() == 'SUBTOTAL' or navio_cell.upper() == 'SUBTOTAL':
                # SUBTOTAL fecha a tabela real de pedidos. Tudo depois dela
                # (mini-tabela STATUS/%, células soltas de SALDO/DÍVIDA etc.)
                # fica fora da tabela por definição — parar aqui, não só pular
                # a linha (ver 14/07/2026, aba NHoGSampaio).
                if numero.upper() == 'SUBTOTAL' or navio_cell.upper() == 'SUBTOTAL':
                    break
                continue
            # SITUAÇÃO: texto da col 17 tem prioridade; cor da linha é fallback
            bg = r[0][1]
            sit_txt = _txt(r, 17).upper()
            situacao = TEXTO_SITUACAO.get(sit_txt, '') or COR_SITUACAO.get(bg, '')
            # Aditamento = FR-171 (6) + ADT 01 (7)
            adit = ' + '.join(v for v in (_txt(r, 6), _txt(r, 7)) if v)
            # MSG: cada coluna vira uma linha rotulada em msgOmps/msgNav
            msgs = {'msgOmps': [], 'msgNav': []}
            for i, rotulo, destino in MSG_COLS:
                v = _txt(r, i)
                if v:
                    msgs[destino].append('%s: %s' % (rotulo, v))
            orcamento = _txt(r, 5)
            # Recurso Indicado Integral: quando a situação é "Recurso Indicado" e a
            # planilha não repete o valor na col REC IND (preenchedor só marca a
            # situação), o valor indicado é o próprio Orçamento (visto em
            # AvHoFluRioTocantins #0001/#0002, 15/07/2026 — não é bug de parsing,
            # é convenção da planilha para "indicado integral").
            recInd = _txt(r, 8) or _txt(r, 9)
            if not recInd and situacao == 'Recurso Indicado':
                recInd = orcamento
            pedidos.append({
                'navio': navio, 'tipo': tipo,
                'numero': numero,
                'descricao': _txt(r, 2),
                'omps': _txt(r, 3),
                'ds': _txt(r, 4),
                'orcamento': orcamento,
                'aditamentos': adit,
                'recInd': recInd,
                'faltaIndicar': _txt(r, 10),
                'altEscopo': _txt(r, 11),
                'msgOmps': '\n'.join(msgs['msgOmps']),
                'msgNav': '\n'.join(msgs['msgNav']),
                'situacao': situacao,
                'situacaoCor': bg or '',
                'altcredBnvc': _txt(r, 18),
            })
    return pedidos


NSX = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
NSR = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _col_idx(ref):
    """'AB12' -> índice de coluna 0-based."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _detect_ns(workbook_bytes):
    """Descobre o namespace OOXML real a partir da tag raiz de workbook.xml —
    alguns exportadores (01-PPSS-2026-NAVIOS-CORRENTE.xlsx, 16/07/2026) usam
    http://purl.oclc.org/ooxml/... em vez do padrão schemas.openxmlformats.org.
    Retorna (nsx, nsr) para uso em todo o arquivo."""
    root = ET.fromstring(workbook_bytes)
    uri = root.tag[1:root.tag.index('}')] if root.tag.startswith('{') else NSX[1:-1]
    nsx = '{%s}' % uri
    nsr = nsx.replace('spreadsheetml/main', 'officeDocument/relationships') \
             .replace('spreadsheetml/2006/main', 'officeDocument/2006/relationships')
    return nsx, nsr


def _header_map(root, ss, nsx=NSX):
    """Lê a linha 9 (rótulos das colunas) e devolve {rótulo: [índices]} —
    lista porque rótulos como 'FR-170' se repetem (Orçamento e REC IND usam
    o mesmo nome de coluna em posições diferentes).
    O layout de colunas varia entre abas do mesmo xlsx (visto em 15/07/2026:
    SITUAÇÃO na col S numa aba, col U noutra) — resolver pelo texto, não
    por índice fixo."""
    hdr = {}
    for row in root.iter(nsx + 'row'):
        if int(row.get('r')) != 9:
            continue
        for c in row.iter(nsx + 'c'):
            v = c.find(nsx + 'v')
            if v is None or v.text is None:
                continue
            txt = ss[int(v.text)] if c.get('t') == 's' else v.text
            hdr.setdefault(txt.strip().upper(), []).append(_col_idx(c.get('r')))
        break
    return hdr


def _row8_groups(root, ss, nsx=NSX):
    """Lê a linha 8 (rótulos dos grupos de coluna: IDENTIFICAÇÃO, Orçamento,
    Aditamento, REC IND, FALTA INDICAR, MSG, SITUAÇÃO, ALTCRED P/ BNVC,
    OBSERVAÇÕES) e devolve {rótulo: (col_inicial, col_final)} usando os
    merges da linha 8 para achar a largura de cada grupo. Necessário porque
    a sub-coluna 'FR-170' se repete dentro de Orçamento E de REC IND — só
    dá pra separar os dois pelo grupo pai, não pelo rótulo da sub-coluna."""
    merges = {}
    mc = root.find(nsx + 'mergeCells')
    if mc is not None:
        for m in mc:
            ref = m.get('ref')
            a, b = ref.split(':')
            if not a[-1].isdigit() or int(''.join(ch for ch in a if ch.isdigit())) != 8:
                continue
            merges[_col_idx(a)] = _col_idx(b)
    groups = {}
    cols_seen = []
    for row in root.iter(nsx + 'row'):
        if int(row.get('r')) != 8:
            continue
        for c in row.iter(nsx + 'c'):
            v = c.find(nsx + 'v')
            if v is None or v.text is None:
                continue
            txt = (ss[int(v.text)] if c.get('t') == 's' else v.text).strip().upper()
            col = _col_idx(c.get('r'))
            cols_seen.append((col, txt))
        break
    for i, (col, txt) in enumerate(cols_seen):
        end = merges.get(col, cols_seen[i + 1][0] - 1 if i + 1 < len(cols_seen) else col)
        groups[txt] = (col, end)
    return groups


def extrair_xlsx(f, tipo):
    """Colunas resolvidas pelos grupos da linha 8 + sub-cabeçalhos da linha 9
    de cada aba — o layout varia de aba para aba dentro do mesmo arquivo."""
    z = zipfile.ZipFile(f)
    wb_bytes = z.read('xl/workbook.xml')
    nsx, nsr = _detect_ns(wb_bytes)
    ss = [''.join(t.text or '' for t in si.iter(nsx + 't'))
          for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(nsx + 'si')]
    wb = ET.fromstring(wb_bytes)
    rels = {r.get('Id'): r.get('Target')
            for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    # estilos: xf -> cor de preenchimento (fallback de situação, como no ODS)
    st = ET.fromstring(z.read('xl/styles.xml'))
    fills = []
    for fl in st.find(nsx + 'fills'):
        pf = fl.find(nsx + 'patternFill')
        c = pf.find(nsx + 'fgColor') if pf is not None else None
        rgb = c.get('rgb') if c is not None else None
        fills.append(('#' + rgb[2:].lower()) if rgb else None)
    cellxfs = list(st.find(nsx + 'cellXfs'))
    xf_fill = [int(x.get('fillId') or 0) for x in cellxfs]
    # numFmts customizados (ex.: '0000' = zero-padding do N° do pedido) — sem isso a
    # coluna N° perde o padding quando a célula é numérica pura (ex.: '1' vira '0001'
    # só na exibição via formato da célula, visto 16/07/2026 em 01-PPSS-2026-NAVIOS-
    # CORRENTE.xlsx: NHiBTenCastelo/AvHoFluRioTocantins/AvHoFluRioXingu usam numFmtId
    # 166='0000', gerando falso par novo/removido no merge se não for aplicado aqui).
    numfmts = {}
    nf_el = st.find(nsx + 'numFmts')
    if nf_el is not None:
        for fmt in nf_el:
            numfmts[int(fmt.get('numFmtId'))] = fmt.get('formatCode')
    xf_numfmt = [int(x.get('numFmtId') or 0) for x in cellxfs]

    def apply_zero_pad(raw, style_idx):
        """Aplica um formatCode simples de zero-padding tipo '0000' a um valor
        numérico puro. Só cobre o padrão observado (dígitos '0' repetidos); outros
        formatCodes custom são ignorados (devolve o valor cru)."""
        numfmtid = xf_numfmt[style_idx] if style_idx < len(xf_numfmt) else 0
        code = numfmts.get(numfmtid)
        if code and code.strip('0') == '' and code:
            try:
                return str(int(float(raw))).zfill(len(code))
            except ValueError:
                return raw
        return raw

    def fmt_money(v):
        try:
            n = float(v)
        except ValueError:
            return v
        if n == 0:
            return ''
        return ('R$ {:,.2f}'.format(n)
                .replace(',', 'X').replace('.', ',').replace('X', '.'))

    MSG_XLSX = [('OMPS – ORÇ', 'msgOmps'), ('NAV – SOL IND REC', 'msgNav'),
                ('COMINSUP – IND REC', 'msgNav'), ('COMINSUP/NAV – IND REC', 'msgNav'),
                ('COMINSUP/NAVIO – IND REC', 'msgNav'),
                ('OMPS-TÉRMINO', 'msgOmps'), ('SATISFEITO / CANCELADO', 'msgNav')]
    pedidos = []
    for sheet in wb.iter(nsx + 'sheet'):
        navio = sheet.get('name')
        if navio not in NAVIOS:
            continue
        tgt = rels[sheet.get(nsr + 'id')]
        root = ET.fromstring(z.read('xl/' + tgt.lstrip('/')))
        hdr = _header_map(root, ss, nsx)
        grp = _row8_groups(root, ss, nsx)

        def group_cols(label):
            r = grp.get(label)
            return list(range(r[0], r[1] + 1)) if r else []
        c_navio, c_num, c_desc = hdr.get('NAVIO', [0])[0], hdr.get('N°', [1])[0], hdr.get('DESCRIÇÃO', [2])[0]
        c_omps, c_ds = hdr.get('OMPS', [3])[0], hdr.get('DS', [4])[0]
        cols_orc = group_cols('ORÇAMENTO')
        cols_adit = group_cols('ADITAMENTO')
        cols_rec = group_cols('REC IND')
        c_falta = grp.get('FALTA INDICAR', (None,))[0]
        c_altesc = hdr.get('ALT ESCOPO', [None])[0]
        c_sit = grp.get('SITUAÇÃO', (None,))[0]
        c_altcred = grp.get('ALTCRED P/ BNVC', (None,))[0]
        for row in root.iter(nsx + 'row'):
            if int(row.get('r')) < 10:
                continue
            vals, styles_row = {}, {}
            for c in row.iter(nsx + 'c'):
                i = _col_idx(c.get('r'))
                v = c.find(nsx + 'v')
                if v is None or v.text is None:
                    continue
                vals[i] = ss[int(v.text)] if c.get('t') == 's' else v.text
                styles_row[i] = int(c.get('s') or 0)
            numero = str(vals.get(c_num, '')).strip()
            if c_num in styles_row:
                numero = apply_zero_pad(numero, styles_row[c_num])
            navio_cell = str(vals.get(c_navio, '')).strip()
            if numero.upper() == 'SUBTOTAL' or navio_cell.upper() == 'SUBTOTAL':
                break  # mesma blindagem do ODS: nada abaixo do SUBTOTAL
            if not numero:
                continue
            sit_txt = str(vals.get(c_sit, '')).strip().upper() if c_sit is not None else ''
            bg = fills[xf_fill[styles_row.get(c_navio, 0)]] if c_navio in styles_row else None
            situacao = TEXTO_SITUACAO.get(sit_txt, '') or COR_SITUACAO.get(bg or '', '')
            orc = next((str(vals[i]).strip() for i in cols_orc if str(vals.get(i, '')).strip()), '')
            adit = ' + '.join(fmt_money(str(vals.get(i, '')).strip())
                              for i in cols_adit if str(vals.get(i, '')).strip())
            rec = next((str(vals[i]).strip() for i in cols_rec if str(vals.get(i, '')).strip()), '')
            # Recurso Indicado Integral: mesma convenção do ODS (ver comentário em
            # extrair_arquivo) — situação "Recurso Indicado" com REC IND vazio na
            # planilha significa indicado = orçado integralmente.
            if not rec and situacao == 'Recurso Indicado':
                rec = orc
            msgs = {'msgOmps': [], 'msgNav': []}
            for rotulo, destino in MSG_XLSX:
                idxs = hdr.get(rotulo)
                if not idxs:
                    continue
                v = str(vals.get(idxs[0], '')).strip()
                if v:
                    msgs[destino].append('%s: %s' % (rotulo, v))
            pedidos.append({
                'navio': navio, 'tipo': tipo,
                'numero': numero,
                'descricao': str(vals.get(c_desc, '')).strip(),
                'omps': str(vals.get(c_omps, '')).strip(),
                'ds': str(vals.get(c_ds, '')).strip(),
                'orcamento': fmt_money(orc),
                'aditamentos': adit,
                'recInd': fmt_money(rec),
                'faltaIndicar': fmt_money(str(vals.get(c_falta, '')).strip()) if c_falta is not None else '',
                'altEscopo': str(vals.get(c_altesc, '')).strip() if c_altesc is not None else '',
                'msgOmps': '\n'.join(msgs['msgOmps']),
                'msgNav': '\n'.join(msgs['msgNav']),
                'situacao': situacao,
                'situacaoCor': bg or '',
                'altcredBnvc': str(vals.get(c_altcred, '')).strip() if c_altcred is not None else '',
            })
    return pedidos


def extrair(pasta):
    arquivos = sorted(
        f for f in glob.glob(os.path.join(pasta, '*'))
        if f.lower().endswith(('.ods', '.xlsx')) and not os.path.basename(f).startswith('~$'))
    pedidos = []
    ignorados = []
    for f in arquivos:
        nome = os.path.basename(f).upper()
        if 'CORRENTE' in nome:
            tipo = 'Corrente'
        elif 'PROGRAMADA' in nome:
            tipo = 'Programada'
        else:
            ignorados.append(os.path.basename(f))
            continue
        if f.lower().endswith('.xlsx'):
            pedidos.extend(extrair_xlsx(f, tipo))
        else:
            pedidos.extend(extrair_arquivo(f, tipo))
    return {'pedidos': pedidos, 'arquivosIgnorados': ignorados}


if __name__ == '__main__':
    pasta = sys.argv[1] if len(sys.argv) > 1 else '1. leituras/4. ppss'
    print(json.dumps(extrair(pasta), ensure_ascii=False, indent=1))
