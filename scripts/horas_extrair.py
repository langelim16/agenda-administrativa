#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator das planilhas mensais de Horas de Funcionamento dos motores.

Uso: python3 scripts/horas_extrair.py [pasta]
     (padrão: "1. leituras/3. horas-funcionamento")

Cada planilha (aba CHN4) traz o ACUMULADO de horas por motor no fim do mês de
referência (título: "HORAS DE FUNCIONAMENTO ... – JAN2026"). A saída agrupa por
motor (chave = meio+tipo+bordo, com nº de série de conferência) a série mensal
de acumulados e os DELTAS mês a mês — cada delta > 0 vira um lançamento
"+X h (último dia do mês)" no artefato. A primeira planilha disponível é a
baseline (não gera lançamento; define/valida o acumulado inicial do motor).
"""
import zipfile, xml.etree.ElementTree as ET, glob, json, sys, os, re

NS = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
      'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
MESES = {'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
         'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12}
# mapeia o nome do meio na planilha -> chave do navio no artefato (horasShips)
SHIP_KEY_PATTERNS = [
    ('nsampaio', r'sampaio'), ('castelo', r'castelo'),
    ('tocantins', r'tocantins'), ('xingu', r'xingu'),
    ('vega', r'vega'), ('denebola', r'den[eé]bola'),
    ('regulus', r'r[eé]gulus'), ('boto', r'boto'),
]


def num(s):
    s = (s or '').strip()
    if not s or s in ('-', 'NA'):
        return None
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def ship_key(meio):
    m = meio.lower()
    for key, pat in SHIP_KEY_PATTERNS:
        if re.search(pat, m):
            return key
    return None


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
                cells += [txt] * min(rep, 30)
            rows.append(cells)
        return rows
    return []


def extrair(pasta):
    motores = {}   # chave motor -> {info, leituras: {AAAA-MM: acumulado}}
    avisos = []
    arquivos = sorted(
        f for f in glob.glob(os.path.join(pasta, '**', '*'), recursive=True)
        if f.lower().endswith('.ods') and not os.path.basename(f).startswith('~$'))
    for f in arquivos:
        rows = sheet_rows(f, 'CHN4')
        if not rows:
            avisos.append('%s: aba CHN4 não encontrada' % os.path.basename(f))
            continue
        # mês/ano: prioriza o NOME DO ARQUIVO (Ref-MAI2026); o título interno às
        # vezes fica desatualizado (ex.: arquivo MAI2026 com título ABR2026).
        base = os.path.basename(f).upper()
        mes = ano = None
        m = re.search(r'([A-Z]{3})(\d{4})', base)
        if m and m.group(1) in MESES:
            mes, ano = MESES[m.group(1)], int(m.group(2))
        tmes = tano = None
        for r in rows[:4]:
            for c in r:
                mt = re.search(r'([A-Z]{3})\s*(\d{4})', c or '')
                if mt and mt.group(1) in MESES:
                    tmes, tano = MESES[mt.group(1)], int(mt.group(2))
        if not mes:
            mes, ano = tmes, tano
        elif tmes and (tmes, tano) != (mes, ano):
            avisos.append('%s: título interno indica %02d/%04d mas o nome do arquivo indica %02d/%04d — usando o nome do arquivo'
                          % (os.path.basename(f), tmes, tano, mes, ano))
        if not mes:
            avisos.append('%s: mês de referência não identificado' % os.path.basename(f))
            continue
        ref = '%04d-%02d' % (ano, mes)
        for r in rows:
            if len(r) < 10:
                continue
            meio = (r[0] or '').strip()
            key = ship_key(meio)
            if not key:
                continue
            tipo, bordo = (r[3] or '').strip(), (r[4] or '').strip()
            horas = num(r[8])
            if horas is None:
                continue
            mk = '%s|%s|%s' % (key, tipo, bordo)
            m = motores.setdefault(mk, {
                'navio': key, 'meioPlanilha': meio, 'tipoMotor': tipo,
                'bordo': bordo, 'fabricante': (r[5] or '').strip(),
                'modelo': (r[6] or '').strip(), 'numSerie': (r[7] or '').strip(),
                'horasManutencao': num(r[9]), 'leituras': {},
            })
            m['leituras'][ref] = horas
    # deltas mês a mês (lançamentos propostos); delta negativo = acumulado que
    # DIMINUIU entre meses — impossível fisicamente, indica erro na planilha
    # (linhas trocadas, digitação) e vai para revisão em vez de lançamento.
    for m in motores.values():
        refs = sorted(m['leituras'])
        m['lancamentos'] = []
        m['revisar'] = []
        for a, b in zip(refs, refs[1:]):
            delta = round(m['leituras'][b] - m['leituras'][a], 1)
            if delta > 0:
                m['lancamentos'].append({'mesRef': b, 'horas': delta})
            elif delta < 0:
                m['revisar'].append({'mesRef': b, 'delta': delta,
                                     'anterior': m['leituras'][a], 'atual': m['leituras'][b]})
        m['baseline'] = {'mesRef': refs[0], 'acumulado': m['leituras'][refs[0]]} if refs else None
    return {'motores': sorted(motores.values(), key=lambda x: (x['navio'], x['tipoMotor'], x['bordo'])),
            'avisos': avisos}


if __name__ == '__main__':
    pasta = sys.argv[1] if len(sys.argv) > 1 else '1. leituras/3. horas-funcionamento'
    print(json.dumps(extrair(pasta), ensure_ascii=False, indent=1))
