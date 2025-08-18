importaciones
importación re
importar json
importar sqlite3
desde urllib.parse importar urlparse
desde datetime importar datetime
desde flask importar Flask, render_template, solicitud, jsonify, enviar_archivo
desde flask_sqlalchemy importar SQLAlchemy
desde sqlalchemy importar func
desde flask_socketio importar SocketIO, emitir
importar csv
desde io importar StringIO, BytesIO

aplicación = Flask(__nombre__)
app.config[ 'CLAVE_SECRETA' ] = os.environ.get( 'CLAVE_SECRETA' , 'dev-secret' )

# Ruta absoluta por defecto para SQLite y JSON (Render: disco efímero; OK para pruebas)
db_path = os.path.abspath( 'golf.db' )
ruta_de_datos = os.environ.get( 'DATA_JSON' , os.path.abspath( 'inscriptos.json' ))
app.config[ 'SQLALCHEMY_DATABASE_URI' ] = os.environ.get( 'DATABASE_URL' , f'sqlite:/// {db_path} ' )
app.config[ 'SQLALCHEMY_TRACK_MODIFICATIONS' ] = Falso
si app.config[ 'SQLALCHEMY_DATABASE_URI' ].startswith( 'sqlite' ):
    app.config[ 'OPCIONES_DE_ENGINE_SQLALCHEMY' ] = { "argumentos_de_conexión" : { "verificar_el_mismo_hilo" : Falso }}

# Clave de admin para borrar (cambiable por variable de entorno)
CLAVE_ADMIN = os.environ.get( 'CLAVE_ADMIN' , 'admin123' )

db = SQLAlchemy(aplicación)
socketio = SocketIO(aplicación, cors_orígenes_permitidos= '*' )

clase Jugador (db.Model):
 
    id = db.Column(db.Integer, clave_principal= True )
    nombre_completo = db.Column(db.String( 160 ), nulo= Falso )
    matricula = db.Column(db.String(40), nullable=False)    # opcional -> '' si vacía
    creado_en = db.Column(db.DateTime, predeterminado=datetime.utcnow, predeterminado_del_servidor=func.now())

    def to_dict ( self ):
 
        devolver {
            'id' : yo mismo . id ,
            'nombre_completo' : self .nombre_completo,
            'matricula': self.matricula,
            'creado_en' : self .creado_en.strftime( '%Y-%m-%d %H:%M' )
        }

def _sqlite_path_from_uri ( uri: str ) -> str :
 
    si no uri.startswith( 'sqlite' ):
 
        devolver '' 
    si uri.endswith( ':memoria:' ):
        devolver ':memoria:' 
    si uri.startswith( 'sqlite:///' ):
        devolver uri.replace( 'sqlite:///' , '' , 1 )
    devuelve urlparse(uri).path

def asegurar_sqlite_columns ():
 
    uri = app.config[ 'URI_BASE_DE_DATOS_SQLALCHEMY' ]
    si no uri.startswith( 'sqlite' ):
 
        devolver
    archivo_base_de_datos = _sqlite_path_from_uri(uri)
    Si no es dbfile:
 
        devolver
    is_memory = (archivo_base_de_datos == ':memoria:' )
    si no es is_memory y no es os.path.exists(dbfile):
  
        devolver

    con = sqlite3.connect(archivo_base_datos)
    cur = con.cursor()
    cur.execute( "SELECCIONAR nombre DE sqlite_master DONDE tipo='tabla' Y nombre='jugador'" )
    fila = cur.fetchone()
    si no fila:
 
        con.close()
        devolver

    cur.execute( "PRAGMA table_info(jugador)" )
    cols = {r[ 1 ] para r en cur.fetchall()}
    cambiado = Falso

    si 'full_name' no está en columnas:
   
        cur.execute( "ALTER TABLE jugador ADD COLUMN nombre_completo VARCHAR(160) PREDETERMINADO ''" )
        si 'nombre' en columnas:
  
            cur.execute( """ACTUALIZAR reproductor
                           SET nombre_completo = COALESCE(nombre_completo, nombre)
                           DONDE (nombre_completo ES NULO O nombre_completo='') Y nombre NO ES NULO""" )
        cambiado = Verdadero

    si 'matricula' no está en cols:
   
        cur.execute( "ALTER TABLE jugador ADD COLUMN matrícula VARCHAR(40) DEFAULT ''" )
        cambiado = Verdadero

    Si se cambia:
        con.commit()
    con.close()

def guardar_json_backup ():
 
    jugadores = Jugador.consulta.order_by(Jugador.id.asc ( )). all ()
    carga útil = { 'actualizado_a_utc' : datetime.utcnow().isoformat(), 'jugadores' : []}
    para p en jugadores:
        d = p.to_dict()
        d[ 'creado_en_iso' ] = p.creado_en.isoformat()
        carga útil[ 'jugadores' ].append(d)
    tmp = ruta_de_datos + '.tmp'
    con abierto (tmp, 'w' , codificación= 'utf-8' ) como f:
 
        json.dump(carga útil, f, asegurar_ascii= Falso , sangría= 2 )
    os.replace(tmp, ruta_de_datos)

def restaurar_desde_json_si_vacío ():
 
    si Player.query.count() > 0 o no os.path.exists(data_path):
  
        devolver
    intentar :
        con abierto (data_path, 'r' , codificación= 'utf-8' ) como f:
 
            datos = json.load(f)
        para el elemento en datos.get( 'jugadores' , []):
            dt = Ninguno
            si item.get( 'creado_en_iso' ):
                intentar :
                    dt = datetime.fromisoformat(item[ 'creado_en_iso' ])
                excepto Excepción:
                    dt = Ninguno
            si dt es Ninguno y item.get( 'created_at' ):
  
                para fmt en ( '%Y-%m-%d %H:%M' , '%Y-%m-%d %H:%M:%S' ):
                    intentar :
                        dt = datetime.strptime(item[ 'creado_en' ], fmt)
                        romper
                    excepto Excepción:
                        aprobar
            dt = dt o datetime.utcnow()
            p = Jugador(
                id =item.get( 'id' ),
                nombre_completo=(item.get( 'nombre_completo' ) o '' ).strip(),
 
                matrícula=(item.get( 'matrícula' ) o '' ).strip(),
 
                creado_en=dt
            )
            db.session.add(p)
        db.session.commit()
    excepto Excepción como e:
        print("No se pudo restaurar desde JSON:", e)

si app.config[ 'SQLALCHEMY_DATABASE_URI' ].startswith( 'sqlite' ):
    asegurar_columnas_sqlite()
con la aplicación.app_context():
    db.create_all()
    restaurar_desde_json_si_está_vacío()

NOMBRE_RE = re. compilar ( r'^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]+$' )

@app.route( '/' )
definición índice ():
 
    jugadores = Jugador.consulta.ordenar_por(Jugador.creado_en.asc()). todos ()
    devuelve render_template( 'index.html' , jugadores=[p.to_dict() para p en jugadores])

@app.route( '/backup.json' )
def descargar_copia de seguridad ():
 
    si no os.path.exists(ruta_de_datos):
 
        guardar_copia_de_seguridad_json()
    devolver enviar_archivo(ruta_de_datos, tipo_mime= 'application/json' , como_archivo_adjunto= True , nombre_descarga= 'inscriptos.json' )

@app.route( '/signup' , métodos=[ 'POST' ] )
definición signup ():
 
    datos = solicitud.get_json(silent= True ) o solicitud.formulario
    nombre_completo = (data.get( 'nombre_completo' ) o data.get( 'nombre' ) o '' ).strip()
 
    matrícula = (data.get( 'matricula' ) o '' ).strip()
 
    si no es nombre_completo:
 
        return jsonify({'ok': False, 'error': 'El apellido y nombre es obligatorio.'}), 400
    si no NOMBRE_RE.fullmatch(nombre_completo):
 
        return jsonify({'ok': False, 'error': 'El apellido y nombre solo admite letras y espacios.'}), 400
    si matrícula y no re.fullmatch( r'\d{1,12}' , matrícula):
 
        return jsonify({'ok': False, 'error': 'La matrícula debe contener solo números (1–12 dígitos).'}), 400
    jugador = Jugador(nombre_completo=nombre_completo, matrícula=matrícula o '' )
 
    db.session.add(jugador)
    db.session.commit()
    guardar_copia_de_seguridad_json()
    carga útil = jugador.to_dict()
    socketio.emit( 'player_added' , carga útil)
    devuelve jsonify({ 'ok' : True , 'player' : payload})

@app.route( '/eliminar/<int:pid>' , métodos=[ 'POST' ] )
def eliminar ( pid ):
 
    datos = solicitud.get_json(silent= True ) o {}
    admin_key = datos.get( 'admin_key' ) o '' 
    si clave_administradora != CLAVE_ADMIN:
        return jsonify({'ok': False, 'error': 'Clave de admin inválida.'}), 403
    p = Jugador.consulta.obtener_o_404(pid)
    db.session.delete(p)
    db.session.commit()
    guardar_copia_de_seguridad_json()
    socketio.emit( 'jugador_eliminado' , { 'id' : pid})
    devuelve jsonify({ 'ok' : True })

@app.route( '/export.csv' )
def export_csv ():
 
    jugadores = Jugador.consulta.ordenar_por(Jugador.creado_en.asc()). todos ()
    si = StringIO()
    escritor = csv.escritor(si)
    escritor.writerow([ 'id' , 'nombre_completo' , 'matrícula' , 'creado_en' ])
    para p en jugadores:
        escritor.writerow([p. id , p.nombre_completo, p.matricula, p.creado_en.isoformat()])
    biografía = BytesIO(si.getvalue().encode( 'utf-8-sig' ))
    bio.seek( 0 )
    devolver enviar_archivo(bio, tipo mime= 'texto/csv' , como_archivo_adjunto= True , nombre_descarga= 'inscriptos.csv' )

@socketio.on( 'conectar' )
def handle_connect ():
 
    jugadores = Jugador.consulta.ordenar_por(Jugador.creado_en.asc()). todos ()
    emit( 'bootstrap' , [p.to_dict() para p en jugadores])

si __nombre__ == '__principal__' :
    socketio.run(aplicación, host= '0.0.0.0' , puerto= int (os.environ.get( 'PUERTO' , 5000 )), depuración= True )
