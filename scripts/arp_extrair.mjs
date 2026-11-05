// Extrai as demandas do CHN-4 e meios subordinados nas Atas de Registro de Preços
// (CeIMBe/BNVC) listadas em lic_data (index.html) e regrava o bloco lic_data.
//
// Uso (na raiz do repo, com acesso a pncp.gov.br):
//   npm i --no-save pdfjs-dist@4.6.82
//   node scripts/arp_extrair.mjs            # extrai, valida contra Rio Tocantins e grava index.html
//   node scripts/arp_extrair.mjs --dry      # só relatório, não grava
//
// Linhas do Rio Tocantins já existentes (carga do avhoto, inclui OCR) são mantidas como estão;
// os demais meios são extraídos dos PDFs. Desc/CATMAT/preço de um (ata,item) já conhecido são
// reaproveitados; os novos vêm da API do PNCP (descricao, unidadeMedida, valorUnitarioHomologado).
import fs from 'node:fs';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';

const DRY = process.argv.includes('--dry');
const HTML = 'index.html';
const CACHE = '.arp_cache'; fs.mkdirSync(CACHE, { recursive: true });
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase();

const OMS = ['CHN-4', 'Garnier Sampaio', 'Tenente Castelo', 'Rio Tocantins', 'Rio Xingu'];
const OM_RX = [
  /HIDROGRAFIA E NAVEGACAO DO NORTE|\bCHN[\s-]*4\b|784510/,
  /GARNIER|784513/,
  /CASTELO|784514/,
  /TOCANTIN|784515/,
  /XINGU|784516/,
];
const TOC = 3;

const html = fs.readFileSync(HTML, 'utf8');
const mm = html.match(/(<script id="lic_data" type="application\/json">)([\s\S]*?)(<\/script>)/);
const DATA = JSON.parse(mm[2]);
DATA.m = OMS;

async function get(url, kind) {
  const f = CACHE + '/' + url.replace(/[^\w]+/g, '_').slice(-150) + (kind === 'json' ? '.json' : '.pdf');
  if (fs.existsSync(f)) { const b = fs.readFileSync(f); return kind === 'json' ? JSON.parse(b) : b; }
  for (let t = 0; t < 4; t++) {
    try {
      const r = await fetch(url);
      if (r.status === 404 || r.status === 204) { fs.writeFileSync(f, kind === 'json' ? 'null' : ''); return kind === 'json' ? null : Buffer.alloc(0); }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const b = Buffer.from(await r.arrayBuffer());
      fs.writeFileSync(f, b);
      return kind === 'json' ? JSON.parse(b) : b;
    } catch (e) { if (t === 3) throw e; await new Promise(r => setTimeout(r, 1500 * (t + 1))); }
  }
}

async function tokens(buf) {
  const doc = await pdfjs.getDocument({ data: new Uint8Array(buf), verbosity: 0 }).promise;
  const pages = [];
  for (let p = 1; p <= doc.numPages; p++) {
    const pg = await doc.getPage(p);
    const tc = await pg.getTextContent();
    pages.push(tc.items.filter(i => i.str && i.str.trim()).map(i => ({
      x: Math.round(i.transform[4]), y: Math.round(i.transform[5]), s: i.str.trim() })));
    pg.cleanup();
  }
  await doc.destroy();
  return pages;
}

function lines(toks, tol = 5) {
  const s = [...toks].sort((a, b) => b.y - a.y || a.x - b.x);
  const rows = [];
  for (const t of s) { const l = rows[rows.length - 1]; if (l && Math.abs(l.y - t.y) <= tol) l.t.push(t); else rows.push({ y: t.y, t: [t] }); }
  return rows.map(r => ({ y: r.y, txt: r.t.sort((a, b) => a.x - b.x).map(x => x.s).join(' ').replace(/\s+/g, ' ').trim(), t: r.t }));
}

// mesmo parser do harness do navegador (skill atas-demandas-navio): ver as 3 armadilhas lá
function parse(pages) {
  const all = [];
  pages.forEach((p, pi) => lines(p, 5).forEach(l => all.push({ pi, y: l.y, txt: l.txt, t: l.t })));
  const joined = all.map(l => l.txt).join('\n');
  const rxOM = /^(Órgão\s+Gerenciador|Órgão\s+Participante\s*\d*)\s*[:\-]\s*(.*)$/i;
  const rxQ = /^(QTD|QUANT|QUANTI|QUANTIDADE|QDE)/i;
  const oms = []; let cur = null, cols = null, stop = false;
  for (let i = 0; i < all.length; i++) {
    const L = all[i];
    if (/^4(\.\d)?\s+(DA ADESÃO|DA UTILIZAÇÃO)/i.test(L.txt)) stop = true;
    const mo = L.txt.match(rxOM);
    if (mo) {
      stop = false; let nm = mo[2], j = i;
      while (!/Local de Entrega/i.test(nm) && j + 1 < all.length && (j - i) < 3 && !rxOM.test(all[j + 1].txt)
             && !/\b(ITEM|CATMAT|ESPECIF)/i.test(all[j + 1].txt)) { j++; nm += ' ' + all[j].txt; }
      nm = nm.replace(/\s*Local de Entrega.*$/i, '').replace(/\s+/g, ' ').trim();
      cur = { nome: nm, itens: [] }; oms.push(cur); i = j; continue;
    }
    if (stop || !cur) continue;
    const hc = L.t.find(t => /^CATMAT/i.test(t.s)), hi = L.t.find(t => /^ITEM/i.test(t.s));
    if (hc && hi) {
      let hq = L.t.find(t => rxQ.test(t.s));
      for (let j2 = Math.max(0, i - 2); j2 <= Math.min(all.length - 1, i + 2) && !hq; j2++) { if (all[j2].pi === L.pi) hq = all[j2].t.find(t => rxQ.test(t.s)); }
      cols = { c: hc.x, q: hq ? hq.x : null, i: hi.x }; continue;
    }
    if (!cols) continue;
    const it = L.t.find(t => Math.abs(t.x - cols.i) <= 18 && /^\d{1,4}$/.test(t.s));
    if (!it) continue;
    let qt = null;
    if (cols.q != null) { let bq = 1e9; for (const t of L.t) if (/^\d[\d.,]*$/.test(t.s) && t.x > cols.c) { const d = Math.abs(t.x - cols.q); if (d <= 60 && d < bq) { bq = d; qt = t.s; } } }
    if (qt == null) { let bx = -1; for (const t of L.t) if (/^\d[\d.,]*$/.test(t.s) && t.x > cols.c + 30 && t.x > bx) { bx = t.x; qt = t.s; } }
    let cm = null, best = 1e9;
    for (let j2 = Math.max(0, i - 2); j2 <= Math.min(all.length - 1, i + 2); j2++) {
      if (all[j2].pi !== L.pi) continue;
      for (const t of all[j2].t) if (Math.abs(t.x - cols.c) <= 30 && /^\d{4,7}$/.test(t.s)) { const d = Math.abs(all[j2].y - L.y); if (d < best) { best = d; cm = t.s; } }
    }
    const uf = L.t.find(t => /^[A-ZÇ]{1,6}\.?$/.test(t.s) && t.x > cols.c + 30);
    cur.itens.push([+it.s, cm, qt, uf ? uf.s : null]);
  }
  return { oms, nchar: joined.length, joined: norm(joined) };
}

const num = s => { if (s == null) return null; s = String(s); if (/,/.test(s)) s = s.replace(/\./g, '').replace(',', '.'); else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, ''); const v = Number(s); return isNaN(v) ? null : v; };

// (ata,item) → [desc,catmat,un,pu] já conhecido
const known = {};
for (const d of DATA.d) known[d[0] + '|' + d[1]] = [d[2], d[3], d[4], d[6]];
const itensCompra = {};

const novos = [], rep = { scan: [], erro: [], semNome: {}, toc: { igual: 0, dif: [] } };
for (let ai = 0; ai < DATA.a.length; ai++) {
  const a = DATA.a[ai], url = a[8];
  const m = url && url.match(/atas\/(\d+)\/(\d{4})\/(\d+)\/(\d+)/);
  if (!m) { rep.erro.push([ai, 'sem link']); continue; }
  const [, cnpj, ano, seq, ata] = m;
  let pages;
  try { pages = await tokens(await get(`https://pncp.gov.br/pncp-api/v1/orgaos/${cnpj}/compras/${ano}/${seq}/atas/${ata}/arquivos/1`, 'pdf')); }
  catch (e) { rep.erro.push([ai, String(e.message || e).slice(0, 60)]); continue; }
  const r = parse(pages);
  if (r.nchar < 500) { rep.scan.push([ai, url, OM_RX.map((rx, k) => rx.test(r.joined) ? OMS[k] : null).filter(Boolean)]); continue; }
  const porOm = OMS.map(() => []);
  for (const o of r.oms) { const n = norm(o.nome); OM_RX.forEach((rx, k) => { if (rx.test(n)) porOm[k].push(...o.itens); }); }
  // menção ao meio sem bloco extraído = provável falha do parser
  OM_RX.forEach((rx, k) => { if (rx.test(r.joined) && !porOm[k].length) (rep.semNome[OMS[k]] = rep.semNome[OMS[k]] || []).push(ai); });
  // validação: Rio Tocantins extraído × carga existente
  const tExist = DATA.d.filter(d => d[0] === ai && d[7] === TOC).length;
  if (porOm[TOC].length === tExist) rep.toc.igual++; else rep.toc.dif.push([ai, tExist, porOm[TOC].length]);
  for (let k = 0; k < OMS.length; k++) {
    if (k === TOC) continue;
    for (const [item, cm, qt, un] of porOm[k]) {
      let kn = known[ai + '|' + item];
      if (!kn) {
        const ck = cnpj + '/' + ano + '/' + seq;
        if (!itensCompra[ck]) itensCompra[ck] = (await get(`https://pncp.gov.br/api/pncp/v1/orgaos/${cnpj}/compras/${ano}/${seq}/itens?pagina=1&tamanhoPagina=500`, 'json')) || [];
        const api = itensCompra[ck].find(x => x.numeroItem === item) || {};
        let pu = null;
        try {
          const res = (await get(`https://pncp.gov.br/api/pncp/v1/orgaos/${cnpj}/compras/${ano}/${seq}/itens/${item}/resultados`, 'json')) || [];
          const f = String(a[9] || '').replace(/\D/g, '');
          const hit = res.find(x => String(x.niFornecedor || '').replace(/\D/g, '') === f) || (res.length === 1 ? res[0] : null);
          if (hit) pu = hit.valorUnitarioHomologado ?? null;
        } catch (e) { }
        kn = [api.descricao || '', cm || '', api.unidadeMedida || un || '', pu];
        known[ai + '|' + item] = kn;
      }
      novos.push([ai, item, kn[0], cm || kn[1] || '', kn[2] || un || '', num(qt) ?? '', kn[3] ?? '', k]);
    }
  }
  if (ai % 20 === 0) console.error(`${ai + 1}/${DATA.a.length}`);
}

const cont = {}; novos.forEach(d => cont[OMS[d[7]]] = (cont[OMS[d[7]]] || 0) + 1);
console.log(JSON.stringify({ novosPorMeio: cont, tocantinsIgual: rep.toc.igual, tocantinsDif: rep.toc.dif.length, tocDifAmostra: rep.toc.dif.slice(0, 15),
  digitalizadas: rep.scan.length, digitalizadasComMeio: rep.scan.filter(s => s[2].some(x => x !== 'Rio Tocantins')), erros: rep.erro,
  mencaoSemItens: rep.semNome }, null, 1));
fs.writeFileSync('.arp_cache/relatorio.json', JSON.stringify({ rep, cont }, null, 1));

if (!DRY) {
  DATA.d = DATA.d.filter(d => d[7] === TOC).concat(novos);
  DATA.d.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[7] - y[7]);
  const s = JSON.stringify(DATA);
  fs.writeFileSync(HTML, html.slice(0, mm.index) + mm[1] + s + mm[3] + html.slice(mm.index + mm[0].length));
  console.error('index.html gravado: ' + DATA.d.length + ' linhas');
}
