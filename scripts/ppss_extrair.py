#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator dos Pedidos de Serviço dos Meios (PPSS) das planilhas ODS
(pasta "1. leituras/4. ppss/").

Uso: python3 scripts/ppss_extrair.py [pasta]   (padrão: "1. leituras/4. ppss")
Saída: JSON com um pedido por linha, pronto para conferência e posterior
substituição de aa_ppss_v1 no Supabase do artefato.

Regras de mapeamento (definidas com o usuário em 2026-07-14):
- Duas planilhas por leitura: "...CORRENTE.ods" -> tipo Corrente,
  "...PROGRAMADAS.ods" -> tipo Programada. Uma aba por navio (mesmos 4
  nomes das duas planilhas = PPSS_NAVIOS do app).
- Situação vem da COR DE FUNDO da linha, não de texto (a planilha usa cor
  como o próprio dado de status). Mapeamento fixo (legenda em B2:B7 de cada
  aba, estável entre os dois arquivos):
    #33cccc -> Concluído          #ff0000 -> Cancelado
    #dc85e9 -> Falta Indicar      #2cee0e -> Recurso Indicado
    #ffcc99 -> Orçado e não Indicado   #536dfe -> Não orçado
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
NAVIOS = ['NHoGSampaio', 'NHiBTenCastelo', 'AvHoFluRioTocantins', 'AvHoFluRioXingu']


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
                if not tc.tag.endswith('}table-cell'):
                    continue
                rep = int(tc.get('{%s}number-columns-repeated' % NS['t']) or 1)
                txt = ' '.join(''.join(p.itertext())
                               for p in tc.iter('{%s}p' % NS['x']))
                bg = styles.get(tc.get('{%s}style-name' % NS['t']))
                cells += [(txt, bg)] * min(rep, 20)
            if rep_row > 1 and not any(c[0] for c in cells):
                continue
            rows.append(cells)
        return rows
    return []


def extrair_arquivo(f, tipo):
    root = ET.fromstring(zipfile.ZipFile(f).read('content.xml'))
    styles = cell_styles_bg(root)
    pedidos = []
    for navio in NAVIOS:
        rows = sheet_rows(root, navio, styles)
        if not rows:
            continue
        for r in rows[9:]:
            navio_cell = r[0][0].strip() if len(r) > 0 else ''
            numero = r[1][0].strip() if len(r) > 1 else ''
            if not numero or numero.upper() == 'SUBTOTAL' or navio_cell.upper() == 'SUBTOTAL':
                # SUBTOTAL fecha a tabela real de pedidos. Tudo depois dela
                # (mini-tabela STATUS/%, células soltas de SALDO/DÍVIDA etc.)
                # fica fora da tabela por definição — parar aqui, não só pular
                # a linha, senão dado solto caindo sobre alguma coluna vira
                # pedido fantasma (ver 14/07/2026, aba NHoGSampaio).
                if numero.upper() == 'SUBTOTAL' or navio_cell.upper() == 'SUBTOTAL':
                    break
                continue
            bg = r[0][1]
            situacao = COR_SITUACAO.get(bg, '')
            pedidos.append({
                'navio': navio, 'tipo': tipo,
                'numero': numero,
                'descricao': r[2][0].strip() if len(r) > 2 else '',
                'omps': r[3][0].strip() if len(r) > 3 else '',
                'ds': r[4][0].strip() if len(r) > 4 else '',
                'orcamento': r[5][0].strip() if len(r) > 5 else '',
                'aditamentos': r[6][0].strip() if len(r) > 6 else '',
                'altEscopo': r[11][0].strip() if len(r) > 11 else '',
                'situacao': situacao,
                'situacaoCor': bg or '',
            })
    return pedidos


def extrair(pasta):
    arquivos = sorted(
        f for f in glob.glob(os.path.join(pasta, '*'))
        if f.lower().endswith('.ods') and not os.path.basename(f).startswith('~$'))
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
        pedidos.extend(extrair_arquivo(f, tipo))
    return {'pedidos': pedidos, 'arquivosIgnorados': ignorados}


if __name__ == '__main__':
    pasta = sys.argv[1] if len(sys.argv) > 1 else '1. leituras/4. ppss'
    print(json.dumps(extrair(pasta), ensure_ascii=False, indent=1))
