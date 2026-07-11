#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator de comissões do CHN-4 a partir dos PDFs do PMPE.

Uso: python3 scripts/pmpe_extrair.py [pasta]   (padrão: "1. leituras/2. pmpe")
Saída: JSON (stdout) com um evento por comissão de meio do artefato
(NHo Garnier Sampaio, NHiB Tenente Castelo, AvHoFlu Rio Tocantins/Xingu,
AvB Vega/Denebola/Regulus/Boto), pronto para conferência e posterior
registro na aba "Comissões" do CONDEF.

Avisos de parsing (chunk ilegível, unidade não reconhecida etc.) vão
para stderr — stdout fica só com o JSON.
"""
import glob, json, os, re, sys
from pdfminer.high_level import extract_text

MESES = {'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
         'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12}
MEIOS_ARTEFATO = ['NHo Garnier Sampaio', 'NHiB Tenente Castelo',
                  'AvHoFlu Rio Tocantins', 'AvHoFlu Rio Xingu',
                  'AvB Vega', 'AvB Denebola', 'AvB Regulus', 'AvB Boto']
# parte distintiva de cada meio, usada para casar por substring na UNIDADE
DISTINTIVO = {m: m.split(' ', 1)[1] if m.split(' ', 1)[0] != 'AvB'
              else m.split(' ')[-1] for m in MEIOS_ARTEFATO}

JUNK_RE = re.compile(
    r'^(DOCUMENTO PREPARAT|Art\. 3|MARINHA DO BRASIL|COMANDO DO|'
    r'Programa de Movi|EVENTO$|GRUPAMENTO|UNIDADE$|PER[ÍI]ODO$|'
    r'[ÁA]REA/PORTO|OPERA[ÇC][ÕO]ES/EXERC|OBSERVA[ÇC][ÕO]ES$|M[ÊE]S:|'
    r'- \d+ de \d+ -|EVT \d|Ap[d]? |Item )')
CODE_RE = re.compile(r'(\d{2})\.(\d{2})\s*\n\(?(PMPE|ADM)\)?')
DUR_RE = re.compile(r'Dura[çc][ãa]o:\s*(\d+)\s*DC')
PERIODO_SIMPLES_RE = re.compile(r'^(\d{2})\s*a\s*(\d{2})$')
PERIODO_MES_RE = re.compile(
    r'^(\d{2})([A-ZÇ]{3})?\s*\n?\s*a\s*\n?\s*(\d{2})([A-ZÇ]{3})?$')


def norm(s):
    """Normaliza texto de PDF: desfaz hifenização, aspas curvas, espaços."""
    s = re.sub(r'-\s*\n\s*', '', s)          # junta palavra hifenizada quebrada
    s = s.replace('\n', ' ')
    s = s.replace('“', '"').replace('”', '"').replace("'", '"')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def identifica_meio(unidade_norm):
    for meio, dist in DISTINTIVO.items():
        if dist.lower() in unidade_norm.lower():
            return meio
    return None


def resolve_periodo(periodo_txt, mes_ref, ano_ref):
    """Retorna (dataInicio, dataFim) em AAAA-MM-DD a partir do texto bruto."""
    t = periodo_txt.strip()
    m = PERIODO_SIMPLES_RE.match(re.sub(r'\s+', '', t.replace('\n', '')))
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        di = '%04d-%02d-%02d' % (ano_ref, mes_ref, d1)
        df = '%04d-%02d-%02d' % (ano_ref, mes_ref, d2)
        return di, df
    m = PERIODO_MES_RE.match(t)
    if m:
        d1, mes1, d2, mes2 = m.groups()
        d1, d2 = int(d1), int(d2)
        mes1n = MESES.get(mes1) if mes1 else mes_ref
        mes2n = MESES.get(mes2) if mes2 else mes_ref
        ano1 = ano_ref
        ano2 = ano_ref if mes2n >= mes1n else ano_ref + 1
        di = '%04d-%02d-%02d' % (ano1, mes1n, d1)
        df = '%04d-%02d-%02d' % (ano2, mes2n, d2)
        return di, df
    return None, None


def parse_chunk(chunk, arquivo, mes, ano, nevt, tipo):
    linhas = [norm(p) for p in re.split(r'\n\s*\n', chunk)]
    linhas = [l for l in linhas if l and not JUNK_RE.match(l)]
    if not linhas or linhas[0] != 'XXX':
        return None
    # campos em ordem: XXX(gpt op), UNIDADE, PERÍODO, ÁREA, OPERAÇÃO, PROPÓSITO, OBSERVAÇÕES...
    idx = 0
    idx += 1  # pula "XXX" (grupamento operativo)
    if idx >= len(linhas):
        return None
    unidade = linhas[idx]; idx += 1
    meio = identifica_meio(unidade)
    if meio is None:
        return None  # não é meio do artefato, ignora silenciosamente
    if idx >= len(linhas):
        return None
    periodo_txt = linhas[idx]; idx += 1
    area = linhas[idx] if idx < len(linhas) else ''; idx += 1
    operacao = linhas[idx] if idx < len(linhas) else ''; idx += 1
    proposito = linhas[idx] if idx < len(linhas) else ''; idx += 1
    observ = ' '.join(linhas[idx:])
    data_inicio, data_fim = resolve_periodo(periodo_txt, mes, ano)
    dm = DUR_RE.search(observ)
    duracao = int(dm.group(1)) if dm else None
    return {
        'arquivo': os.path.basename(arquivo), 'mes': mes, 'ano': ano,
        'nEvt': nevt, 'tipo': tipo, 'meio': meio,
        'periodoTexto': periodo_txt, 'dataInicio': data_inicio,
        'dataFim': data_fim, 'duracaoDias': duracao, 'area': area,
        'operacao': operacao, 'proposito': proposito,
    }


def mes_ano_do_nome(nome):
    m = re.search(r'([A-ZÇ]{3})-(\d{4})', nome.upper())
    if not m:
        return None, None
    return MESES.get(m.group(1)), int(m.group(2))


def extrair(pasta):
    resultados = []
    arquivos = sorted(glob.glob(os.path.join(pasta, '**', 'PMPE *-*.pdf'),
                                 recursive=True))
    for f in arquivos:
        mes, ano = mes_ano_do_nome(os.path.basename(f))
        if not mes:
            print(f'aviso: não consegui inferir mês/ano de {f}', file=sys.stderr)
            continue
        texto = extract_text(f)
        codigos = list(CODE_RE.finditer(texto))
        for i, m in enumerate(codigos):
            nevt = '%s.%s' % (m.group(1), m.group(2))
            tipo = m.group(3)
            fim = codigos[i + 1].start() if i + 1 < len(codigos) else len(texto)
            chunk = texto[m.end():fim]
            try:
                r = parse_chunk(chunk, f, mes, ano, nevt, tipo)
                if r:
                    resultados.append(r)
            except Exception as e:
                print(f'aviso: falha ao parsear evento {nevt} em {f}: {e}',
                      file=sys.stderr)
    return resultados


if __name__ == '__main__':
    pasta = sys.argv[1] if len(sys.argv) > 1 else '1. leituras/2. pmpe'
    print(json.dumps(extrair(pasta), ensure_ascii=False, indent=1))
