# gevent monkey patch DEBE ir primero
from gevent import monkey
monkey.patch_all()

import os
import re
import json
import sqlite3
from urllib.parse import urlparse
from datetime import datetime
from flask import Flask, render_template, render_template_string, request, jsonify, send_file
from jinja2 import TemplateNotFound
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_socketio import SocketIO, emit
import csv
from io import StringIO, BytesIO

# Paths base (Render)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')

# SQLite + JSON (si usás Disk en Render, podés moverlos a /var/data)
db_path = os.path.join(BASE_DIR, 'golf.db')
data_path = os.environ.get('DATA_JSON', os.path.join(BASE_DIR, 'inscriptos.json'))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'check_same_thread': False}}

db = SQLAlchemy(app)

# Socket.IO con WebSocket real (gevent + gevent-websocket)
socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode='gevent',
    logger=False,
    engineio_logger=False,
    ping_interval=25,
    ping_timeout=60
)

# ----------------------- Modelo -----------------------
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)   # Apellido y nombre (obligatorio)
    matricula = db.Column(db.String(40), nullable=False)    # Matrícula opcional -> '' si vacío
    created_at = db.Column(db.DateTime, default=datetime.utcnow, server_default=func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'matricula': self.matricula,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M')
        }

# ----------------- Auto-upgrade de esquema SQLite -----------------
def _sqlite_path_from_uri(uri: str) -> str:
    if not uri.startswith('sqlite'):
        return ''
    if uri.endswith(':memory:'):
        return ':memory:'
    if uri.startswith('sqlite:///'):
        return uri.replace('sqlite:///', '', 1)
    return urlparse(uri).path

def ensure_sqlite_columns():
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    if not uri.startswith('sqlite'):
        return
    dbfile = _sqlite_path_from_uri(uri)
    if not dbfile:
        return
    is_memory = (dbfile == ':memory:')
    if not is_memory and not os.path.exists(dbfile):
        return

    con = sqlite3.connect(dbfile)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player'")
    if not cur.fetchone():
        con.close()
        return

    cur.execute('PRAGMA table_info(player)')
    cols = {r[1] for r in cur.fetchall()}
    changed = False

    if 'full_name' not in cols:
        cur.execute('ALTER TABLE player ADD COLUMN full_name VARCHAR(160) DEFAULT ""')
        if 'name' in cols:
            cur.execute('''UPDATE player
                           SET full_name = COALESCE(full_name, name)
                           WHERE (full_name IS NULL OR full_name="") AND name IS NOT NULL''')
        changed = True

    if 'matricula' not in cols:
        cur.execute('ALTER TABLE player ADD COLUMN matricula VARCHAR(40) DEFAULT ""')
        changed = True

    if changed:
        con.commit()
    con.close()

# ----------------- Backup / Restore JSON -----------------
def save_json_backup():
    """Guarda todos los jugadores en DATA_JSON de forma atómica."""
    players = Player.query.order_by(Player.id.asc()).all()
    payload = {'updated_at_utc': datetime.utcnow().isoformat(), 'players': []}
    for p in players:
        d = p.to_dict()
        d['created_at_iso'] = p.created_at.isoformat()
        payload['players'].append(d)
    tmp = data_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, data_path)

def restore_from_json_if_empty():
    """Si la tabla está vacía y existe el JSON, restaura los datos a la DB."""
    if Player.query.count() > 0 or not os.path.exists(data_path):
        return
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data.get('players', []):
            dt = None
            if item.get('created_at_iso'):
                try:
                    dt = datetime.fromisoformat(item['created_at_iso'])
                except Exception:
                    dt = None
            if dt is None and item.get('created_at'):
                for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
                    try:
                        dt = datetime.strptime(item['created_at'], fmt)
                        break
                    except Exception:
                        pass
            dt = dt or datetime.utcnow()
            p = Player(
                id=item.get('id'),
                full_name=(item.get('full_name') or '').strip(),
                matricula=(item.get('matricula') or '').strip(),
                created_at=dt
            )
            db.session.add(p)
        db.session.commit()
    except Exception as e:
        print('No se pudo restaurar desde JSON:', e)

# ----------------- Init DB + Restore -----------------
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
    ensure_sqlite_columns()
with app.app_context():
    db.create_all()
    restore_from_json_if_empty()

# ----------------- Rutas -----------------
NAME_RE = re.compile(r'^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]+$')

@app.route('/', methods=['GET', 'HEAD'])
def index():
    if request.method == 'HEAD':
        return '', 200
    players = Player.query.order_by(Player.created_at.asc()).all()
    context = {'players': [p.to_dict() for p in players]}
    try:
        return render_template('index.html', **context)
    except TemplateNotFound:
        # Fallback mínimo si falta templates/index.html
        return render_template_string("""
        <!doctype html>
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Matungo Golf</title></head>
        <body style="font-family:system-ui,Arial,sans-serif;padding:2rem">
          <h1>Matungo Golf</h1>
          <p><strong>Nota:</strong> falta <code>templates/index.html</code>. Mostrando vista mínima.</p>
          <h3>Inscriptos</h3>
          <ul>
          {% for p in players %}
            <li>#{{p.id}} — {{p.full_name}} {% if p.matricula %}(Mat: {{p.matricula}}){% endif %} — {{p.created_at}}</li>
          {% else %}
            <li>No hay inscriptos todavía.</li>
          {% endfor %}
          </ul>
          <p>Exportar: <a href="/export.csv">CSV</a> • <a href="/backup.json">Backup JSON</a></p>
        </body></html>
        """, **context), 200

@app.route('/healthz', methods=['GET', 'HEAD'])
def healthz():
    return ('ok', 200)

@app.route('/backup.json')
def download_backup():
    if not os.path.exists(data_path):
        save_json_backup()
    return send_file(data_path, mimetype='application/json', as_attachment=True, download_name='inscriptos.json')

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or request.form
    full_name = (data.get('full_name') or data.get('name') or '').strip()
    matricula = (data.get('matricula') or '').strip()

    if not full_name:
        return jsonify({'ok': False, 'error': 'El apellido y nombre es obligatorio.'}), 400
    if not NAME_RE.fullmatch(full_name):
        return jsonify({'ok': False, 'error': 'El apellido y nombre solo admite letras y espacios.'}), 400
    if matricula and not re.fullmatch(r'\d{1,12}', matricula):
        return jsonify({'ok': False, 'error': 'La matrícula debe contener solo números (1–12 dígitos).'}), 400

    player = Player(full_name=full_name, matricula=matricula or '')
    db.session.add(player)
    db.session.commit()

    save_json_backup()

    payload = player.to_dict()
    socketio.emit('player_added', payload)
    return jsonify({'ok': True, 'player': payload})

@app.route('/export.csv')
def export_csv():
    players = Player.query.order_by(Player.created_at.asc()).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['id', 'full_name', 'matricula', 'created_at'])
    for p in players:
        writer.writerow([p.id, p.full_name, p.matricula, p.created_at.isoformat()])
    bio = BytesIO(si.getvalue().encode('utf-8-sig'))
    bio.seek(0)
    return send_file(bio, mimetype='text/csv', as_attachment=True, download_name='inscriptos.csv')

@socketio.on('connect')
def handle_connect():
    players = Player.query.order_by(Player.created_at.asc()).all()
    emit('bootstrap', [p.to_dict() for p in players])
