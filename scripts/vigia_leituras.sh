#!/bin/bash
# Vigia da pasta "1. leituras/" — disparado pelo launchd (WatchPaths) quando
# algo muda. Detecta arquivos novos/alterados, mapeia pra o skill de
# importação correspondente e roda `claude -p` headless pra importar.
#
# IMPORTANTE — deploy: o plist do LaunchAgent
# (~/Library/LaunchAgents/com.lucasangelim.agenda-leituras.plist) aponta
# para ~/.local/agenda-vigia/vigia_leituras.sh, uma CÓPIA deste arquivo —
# não este caminho em ~/Documents diretamente. O TCC do macOS nega ao
# launchd o spawn de um binário cujo caminho fica dentro de ~/Documents
# (exit 78/EX_CONFIG), então o script executável precisa morar fora dali.
# Após editar este arquivo, sincronizar:
#   cp scripts/vigia_leituras.sh ~/.local/agenda-vigia/vigia_leituras.sh
# Ler o conteúdo de ~/Documents (LEITURAS abaixo) funciona normalmente já
# rodando de fora — só o local do executável e dos artifacts de runtime
# (estado/lock/log) importa ficar fora de ~/Documents.
set -u
DIR="/Users/lucasangelim/Documents/agenda-administrativa"
LEITURAS="$DIR/1. leituras"
# Runtime artifacts ficam em ~/.local/agenda-vigia (fora de ~/Documents)
# pra evitar bloqueio do TCC do macOS em contextos LaunchAgent.
STATE_DIR="$HOME/.local/agenda-vigia"
mkdir -p "$STATE_DIR" 2>/dev/null
ESTADO="$STATE_DIR/leituras-estado.json"
LOCK="$STATE_DIR/vigia.lock"
RERUN="$STATE_DIR/vigia.rerun"
LOG="$STATE_DIR/vigia.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# ── lock atômico; evento durante execução vira rerun ──
if ! mkdir "$LOCK" 2>/dev/null; then
  touch "$RERUN"
  log "lock ativo — marcado rerun"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

while true; do
  rm -f "$RERUN"

  # ── debounce: espera 120s de quietude (cap 30min) — cobre download parcial ──
  waited=0
  while [ $waited -lt 1800 ]; do
    recent=$(/usr/bin/find "$LEITURAS" -type f -mmin -2 2>/dev/null | head -1)
    [ -z "$recent" ] && break
    sleep 30; waited=$((waited+30))
  done
  log "debounce ok (aguardou ${waited}s)"

  # ── diff contra estado; imprime "skill<TAB>path" por arquivo novo ──
  NOVOS=$(python3 - "$LEITURAS" "$ESTADO" <<'PY'
import json, os, sys
leituras, estado_path = sys.argv[1], sys.argv[2]
try:
    estado = json.load(open(estado_path))
except Exception:
    estado = {}
SKILLS = {'1. clg': 'clg-import', '2. pmpe': 'pmpe-import',
          '3. horas-funcionamento': 'horas-import', '4. ppss': 'ppss-import'}
novos = []
for root, _, files in os.walk(leituras):
    for f in files:
        if f.startswith('~$') or not f.lower().endswith(('.ods', '.pdf', '.xlsx')):
            continue
        p = os.path.join(root, f)
        rel = os.path.relpath(p, leituras)
        st = os.stat(p)
        cur = {'size': st.st_size, 'mtime': int(st.st_mtime)}
        prev = estado.get(rel)
        if prev and prev.get('size') == cur['size'] and \
           prev.get('mtime') == cur['mtime'] and prev.get('status') == 'ok':
            continue
        pasta = rel.split(os.sep)[0]
        skill = SKILLS.get(pasta, '')
        novos.append((skill, rel))
for skill, rel in novos:
    print(f'{skill}\t{rel}')
PY
)

  if [ -z "$NOVOS" ]; then
    log "nada novo"
  else
    # pasta sem skill mapeado → só avisa
    SEM_SKILL=$(echo "$NOVOS" | awk -F'\t' '$1==""{print $2}')
    if [ -n "$SEM_SKILL" ]; then
      log "pasta sem skill mapeado: $SEM_SKILL"
      osascript -e 'display notification "Pasta nova em 1. leituras sem skill de importação" with title "Vigia leituras"' 2>/dev/null
    fi

    for SKILL in clg-import pmpe-import horas-import ppss-import; do
      ARQS=$(echo "$NOVOS" | awk -F'\t' -v s="$SKILL" '$1==s{print $2}')
      [ -z "$ARQS" ] && continue
      log "novos p/ $SKILL: $(echo "$ARQS" | tr '\n' ' ')"

      # marca tentativa no estado
      python3 - "$LEITURAS" "$ESTADO" "tentado" <<PY
import json, os, sys
leituras, estado_path, status = sys.argv[1], sys.argv[2], sys.argv[3]
arqs = """$ARQS""".strip().split('\n')
try:
    estado = json.load(open(estado_path))
except Exception:
    estado = {}
from datetime import datetime, timezone
for rel in arqs:
    p = os.path.join(leituras, rel)
    if not os.path.exists(p):
        continue
    st = os.stat(p)
    estado[rel] = {'size': st.st_size, 'mtime': int(st.st_mtime),
                   'status': status,
                   'ts': datetime.now(timezone.utc).isoformat(timespec='seconds')}
json.dump(estado, open(estado_path, 'w'), ensure_ascii=False, indent=1)
PY

      cd "$DIR"
      LISTA=$(echo "$ARQS" | sed 's/^/- 1. leituras\//')
      log "rodando claude headless ($SKILL)…"
      # macOS não tem `timeout`; watchdog manual de 30min
      "$HOME/.local/bin/claude" -p "Execute o skill $SKILL para importar os arquivos novos:
$LISTA
Siga as instruções do skill (gravar direto no Supabase; remoções só como sugestão — se houver sugestão de remoção pendente, apenas registre no log e não execute)." \
        --permission-mode acceptEdits \
        --allowedTools 'Bash,Read,Glob,Grep,Skill' >> "$LOG" 2>&1 &
      CPID=$!
      # watchdog: mata claude se passar de 30min
      ( sleep 1800; kill "$CPID" 2>/dev/null ) &
      WPID=$!
      wait "$CPID"; RC=$?
      kill "$WPID" 2>/dev/null; wait "$WPID" 2>/dev/null

      if [ $RC -eq 0 ]; then
        python3 - "$LEITURAS" "$ESTADO" "ok" <<PY
import json, os, sys
leituras, estado_path, status = sys.argv[1], sys.argv[2], sys.argv[3]
arqs = """$ARQS""".strip().split('\n')
estado = json.load(open(estado_path))
for rel in arqs:
    if rel in estado:
        estado[rel]['status'] = status
json.dump(estado, open(estado_path, 'w'), ensure_ascii=False, indent=1)
PY
        log "$SKILL ok"
      else
        log "$SKILL FALHOU (rc=$RC) — fica 'tentado', re-tenta no próximo evento"
      fi
    done
  fi

  # evento chegou enquanto rodava?
  [ -f "$RERUN" ] || break
  log "rerun solicitado — novo ciclo"
done
exit 0
