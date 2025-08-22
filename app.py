# gevent monkey patch DEBE ir primero (para WebSocket real en Render)
from gevent import monkey
monkey.patch_all()

import os
import re
import json
from datetime import datetime
from flask import Flask, render_template, render_template_string, request, jsonify, send_file
from jinja2 import TemplateNotFound
from flask_socketio import SocketIO, emit
import csv
from io import StringIO, BytesIO
from gevent.lock import Semaphore

# --------- App base ---------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')

# No-cache para evitar vistas viejas por navegador/proxy/CDN
@app.after_request
def add_no_cache_headers(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

# --------- Directorio de datos (SIEMPRE escribible) ---------
# Si montás un Disk en Render, seteá DATA_DIR=/var/data. Si no, cae a /tmp.
DATA_DIR = os.environ.get('DATA_DIR') or ('/var/data' if os.path.exists('/var/data') else '/tmp')
os.makedirs(DATA_DIR, exist_ok=True)

DATA_JSON = os.environ.get('DATA_JSON', os.path.join(DATA_DIR, 'inscriptos.json'))

# --------- Config de logos ---------
LOGO_URL = os.environ.get('LOGO_URL', '/static/logo.png')
LOGO_HEADER_URL = os.environ.get('LOGO_HEADER_URL', LOGO_URL)

# --------- Almacenamiento JSON (sin DB) ---------
LOCK = Semaphore()
STORE = {"players": [], "last_id": 0}  # players: [{id, full_name, matricula}]

def load_store():
    global STORE
    if not os.path.exists(DATA_JSON):
        STORE = {"players": [], "last_id": 0}
        return
    try:
        with open(DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        players = data.get('players', [])
        # Normalizo y calculo last_id
        for p in players:
            p['id'] = int(p.get('id', 0))
            p['full_name'] = (p.get('full_name') or '').strip()
            p['matricula'] = (p.get('matricula') or '').strip()
        last_id = max([p['id'] for p in players], default=0)
        STORE = {"players": players, "last_id": data.get('last_id', last_id)}
    except Exception as e:
        print("[JSON] ERROR al cargar store:", e)
        STORE = {"players": [], "last_id": 0}

def save_store():
    tmp = DATA_JSON + '.tmp'
    payload = {
        "updated_at_utc": datetime.utcnow().isoformat(),
        "last_id": STORE["last_id"],
        "players": STORE["players"],
    }
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_JSON)

# Cargar en arranque
load_store()

print(f"[INIT] DATA_DIR={DATA_DIR}")
print(f"[INIT] JSON={DATA_JSON}")
print(f"[INIT] CARGADOS {len(STORE['players'])} jugadores, last_id={STORE['last_id']}")

# --------- Socket.IO ---------
socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='gevent',
    logger=False,
    engineio_logger=False,
    ping_interval=25,
    ping_timeout=60
)

# --------- Validaciones ---------
NAME_RE = re.compile(r"^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s.'-]+$")

# --------- Rutas ---------
@app.route('/', methods=['GET', 'HEAD'])
def index():
    if request.method == 'HEAD':
        return '', 200
    context = {
        'players': STORE["players"],
        'logo_url': LOGO_URL,
        'header_logo_url': LOGO_HEADER_URL
    }
    try:
        return render_template('index.html', **context)
    except TemplateNotFound:
        # Fallback mínimo si falta template
        return render_template_string("""
        <!doctype html>
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Matungo Golf</title>
        <style>
          body{font-family:system-ui,Arial,sans-serif}
          body::before{
            content:""; position:fixed; inset:0;
            background:url('{{ logo_url }}') center/40% no-repeat;
            opacity:.08; filter:grayscale(100%); pointer-events:none; z-index:0;
          }
          .wrap{position:relative; z-index:1; padding:2rem}
        </style>
        </head>
        <body>
          <div class="wrap">
            <h1><img src="{{ header_logo_url }}" alt="Logo" style="height:42px;vertical-align:middle;margin-right:.5rem" onerror="this.style.display='none'"> Matungo Golf</h1>
            <h3>Inscriptos</h3>
            <ul>
            {% for p in players %}
              <li>#{{p.id}} — {{p.full_name}} {% if p.matricula %}(Mat: {{p.matricula}}){% endif %}</li>
            {% else %}
              <li>No hay inscriptos todavía.</li>
            {% endfor %}
            </ul>
            <p>Exportar: <a href="/export.csv">CSV</a> • <a href="/backup.json">Backup JSON</a></p>
          </div>
        </body></html>
        """, **context), 200

@app.route('/healthz', methods=['GET', 'HEAD'])
def healthz():
    return ('ok', 200)

@app.route('/backup.json')
def download_backup():
    # Aseguro grabar antes de servir
    with LOCK:
        save_store()
    return send_file(DATA_JSON, mimetype='application/json', as_attachment=True, download_name='inscriptos.json')

@app.route('/api/players')
def api_players():
    return jsonify(STORE["players"])

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or request.form
    full_name = (data.get('full_name') or data.get('name') or '').strip()
    matricula = (data.get('matricula') or '').strip()

    print('[POST] /signup payload =', {'full_name': full_name, 'matricula': matricula})

    if not full_name:
        return jsonify({'ok': False, 'error': 'El apellido y nombre es obligatorio.'}), 400
    if not NAME_RE.fullmatch(full_name):
        return jsonify({'ok': False, 'error': 'Apellido y nombre inválido. Permitidos: letras, espacios, tildes, apóstrofo (\'), guion (-) y punto (.)'}), 400
    if matricula and not re.fullmatch(r'\d{1,12}', matricula):
        return jsonify({'ok': False, 'error': 'La matrícula debe contener solo números (1–12 dígitos).'}), 400

    with LOCK:
        # Genero ID incremental
        STORE["last_id"] = int(STORE.get("last_id", 0)) + 1
        player = {
            "id": STORE["last_id"],
            "full_name": full_name,
            "matricula": matricula or ""
        }
        STORE["players"].append(player)
        try:
            save_store()
            print('[STORE] Guardado OK -> id', player["id"])
        except Exception as e:
            print('[STORE] ERROR al guardar JSON:', e)
            # Revierto en memoria si falló persistencia
            STORE["players"].pop()
            STORE["last_id"] -= 1
            return jsonify({'ok': False, 'error': 'No se pudo guardar en el servidor.'}), 500

    socketio.emit('player_added', player)
    return jsonify({'ok': True, 'player': player})

@app.route('/export.csv')
def export_csv():
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['id', 'full_name', 'matricula'])
    for p in STORE["players"]:
        writer.writerow([p['id'], p['full_name'], p['matricula']])
    bio = BytesIO(si.getvalue().encode('utf-8-sig'))
    bio.seek(0)
    return send_file(bio, mimetype='text/csv', as_attachment=True, download_name='inscriptos.csv')

@socketio.on('connect')
def handle_connect():
    emit('bootstrap', STORE["players"])



