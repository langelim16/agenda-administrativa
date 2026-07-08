#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator de lançamentos de consumo de CLG das planilhas ODS (aba "Consumos").

Uso: python3 scripts/clg_extrair.py [pasta]   (padrão: CLG/)
Saída: JSON com um lançamento por linha de consumo, pronto para conferência
e posterior registro no Supabase do artefato.

Regras de mapeamento (definidas com o usuário em 2026-07-08):
- Só linhas da OM CHN-4 com algum consumo > 0.
- REF EVT "PMPE" -> consumo Operativo (exige nº do evento + descrição);
  "ADM"/outros -> Administrativo (descrição vira justificativa).
- Produtos do artefato: ODM (Tipo 04M) -> Estoque de ODM; Gasolina (Tipo 01),
  LUB (Tipo 06) e GRAXA (Tipo 08) -> tabela Gasolina/Lubrificantes/Graxas.
  QAV/ODR/Álcool não existem no artefato (reportados como "ignorados").
- Utilizadores que não são meios do artefato (Viaturas, Farol, CHN-4) são
  listados separadamente para decisão do usuário.
"""
import zipfile, xml.etree.ElementTree as ET, glob, json, sys, os

NS = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
      'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
MESES = {'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
         'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12}
# colunas da aba Consumos (índice 0-based)
PROD = [('gasolina', 8), ('qav', 9), ('odm', 10), ('odr', 11),
        ('lub', 12), ('alcool', 13), ('graxa', 14)]
MEIOS_ARTEFATO = ['NHo Garnier Sampaio', 'NHiB Tenente Castelo',
                  'AvHoFlu Rio Tocantins', 'AvHoFlu Rio Xingu',
                  'AvB Vega', 'AvB Denebola', 'AvB Regulus', 'AvB Boto']


def num(s):
    s = (s or '').strip().replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def sheet_rows(f, sheetname):
    root = ET.fromstring(zipfile.ZipFile(f).read('content.xml'))
    for tb in root.iter('{%s}table' % NS['t']):
        if tb.get('{%s}name' % NS['t']) != sheetname:
            continue
        rows = []
        for tr in tb.iter('{%s}table-row' % NS['t']):
            cells = []
            for tc in tr:
                if not tc.tag.endswith('}table-cell'):
                    continue
                rep = int(tc.get('{%s}number-columns-repeated' % NS['t']) or 1)
                txt = ' '.join(''.join(p.itertext())
                               for p in tc.iter('{%s}p' % NS['x']))
                cells += [txt] * min(rep, 60)
            rows.append(cells)
        return rows
    return []


def extrair(pasta):
    out = []
    arquivos = sorted(glob.glob(os.path.join(pasta, '*.ods')) +
                      glob.glob(os.path.join(pasta, '*.ODS')))
    for f in arquivos:
        rows = sheet_rows(f, 'Consumos')
        if not rows:
            continue
        epoca = ''
        for r in rows[:6]:
            for i, c in enumerate(r):
                if c == 'ÉPOCA:' and i + 1 < len(r):
                    epoca = r[i + 1].strip().upper()
        mes = MESES.get(epoca)
        for r in rows:
            if len(r) < 11 or r[1] != 'CHN-4':
                continue
            util = r[7].strip()
            if not util:
                continue
            prods = {k: num(r[i]) for k, i in PROD
                     if i < len(r) and num(r[i]) > 0}
            if not prods:
                continue
            out.append({
                'arquivo': os.path.basename(f), 'epoca': epoca, 'mes': mes,
                'utilizador': util, 'meioDoArtefato': util in MEIOS_ARTEFATO,
                'tipo': 'Operativo' if r[3].strip() == 'PMPE' else 'Administrativo',
                'nEvt': r[4].strip(), 'descricao': r[5].strip(),
                'consumos': prods,
            })
    return out


if __name__ == '__main__':
    pasta = sys.argv[1] if len(sys.argv) > 1 else 'CLG'
    print(json.dumps(extrair(pasta), ensure_ascii=False, indent=1))
