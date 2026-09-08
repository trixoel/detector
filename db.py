# Capa de acceso a datos: todas las consultas SQL del proyecto viven aqui.
# Se usa SQLite (un solo archivo, asistencia.db) para no depender de un servidor de base
# de datos aparte. Cada funcion recibe la conexion (conn) ya abierta con conectar().
import os
import sys
import sqlite3
import numpy as np


def exe_dir():
    """Carpeta donde vive el .exe en si (si esta empaquetado con PyInstaller), o la de
    este archivo .py si se ejecuta como script normal. Se usa para ubicar la carpeta de
    datos compartida al lado del ejecutable (ver base_dir)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    """Carpeta donde PyInstaller deja los recursos empaquetados junto al programa
    (plantillas HTML, etc.). En modo empaquetado es sys._MEIPASS: la carpeta '_internal'
    que PyInstaller crea junto al .exe (tanto en modo --onefile como --onedir) y donde
    coloca todo lo añadido con --add-data. En modo script (desarrollo) es simplemente la
    carpeta de este archivo, igual que antes."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def base_dir():
    """Carpeta donde se guardan los datos (base de datos, fotos, justificantes).
    En modo script (desarrollo) es la propia carpeta del proyecto, igual que siempre.
    En modo empaquetado (.exe) es una carpeta 'datos' compartida, un nivel por encima de
    la carpeta del ejecutable: asi app.exe y reconocer.exe, aunque cada uno viva en su
    propia carpeta (ver seccion de distribucion en el manual), leen y escriben siempre
    la misma base de datos."""
    if getattr(sys, "frozen", False):
        carpeta = os.path.normpath(os.path.join(exe_dir(), "..", "datos"))
        os.makedirs(carpeta, exist_ok=True)
        return carpeta
    return app_dir()


DB_PATH = os.path.join(base_dir(), "asistencia.db")

# Clase y horario de partida: se crean solos la primera vez que se usa la base de datos
# (ver asegurar_clase_por_defecto), para que tanto la version normal como la compilada
# (.exe) funcionen desde el primer arranque sin pasos manuales.
NOMBRE_CLASE_DEFECTO = "2 Bachillerato Tecnologico de Excelencia"
HORA_ENTRADA_DEFECTO = "08:15"

# dia_semana: 0=lunes .. 4=viernes. Cada lista son las asignaturas de ese dia, en orden,
# emparejadas una a una con los tramos horarios de TRAMOS_DEFECTO (mismo indice = mismo hueco)
HORARIO_SEMANAL_DEFECTO = {
    0: ["Matematicas II", "Fisica", "Tecnologia e Ingenieria II", "RECREO",
        "Lengua Castellana y Literatura II", "Ingles II", "Historia de Espana"],
    1: ["Dibujo Tecnico II", "Fisica", "TIC II", "RECREO",
        "Matematicas II", "Historia de Espana", "Educacion Fisica"],
    2: ["Fisica", "Matematicas II", "Lengua Castellana y Literatura II", "RECREO",
        "Tecnologia e Ingenieria II", "Ingles II", "Filosofia"],
    3: ["Matematicas II", "Dibujo Tecnico II", "Ingles II", "RECREO",
        "Fisica", "TIC II", "Historia de Espana"],
    4: ["Lengua Castellana y Literatura II", "Matematicas II", "Filosofia", "RECREO",
        "Tecnologia e Ingenieria II", "Dibujo Tecnico II", "TIC II"],
}

TRAMOS_DEFECTO = [
    ("08:15", "09:10"), ("09:10", "10:05"), ("10:05", "11:00"), ("11:00", "11:30"),
    ("11:30", "12:25"), ("12:25", "13:20"), ("13:20", "14:15"),
]


def conectar():
    """Abre (o crea si no existe) asistencia.db y se asegura de que todas las tablas
    y columnas necesarias existen. Se llama al principio de cada script/peticion web."""
    conn = sqlite3.connect(DB_PATH)
    # personas: cada alumno/persona reconocible, con su "huella facial" (encoding)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            encoding BLOB NOT NULL
        )
    """)
    # asistencias: un registro por cada vez que la camara reconoce a alguien
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asistencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            fecha_hora TEXT NOT NULL,
            foto TEXT,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    # clases: un grupo/curso (ej. "2 Bachillerato..."), con su hora de entrada por defecto
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            hora_entrada TEXT NOT NULL
        )
    """)
    # horario: el horario semanal de cada clase, tramo a tramo (una fila por hora/asignatura/dia)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS horario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clase_id INTEGER NOT NULL,
            dia_semana INTEGER NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fin TEXT NOT NULL,
            asignatura TEXT NOT NULL,
            FOREIGN KEY (clase_id) REFERENCES clases(id)
        )
    """)
    # indice unico sobre horario: evita duplicar un tramo si el script de siembra
    # (seed_datos.py) se ejecuta mas de una vez por error, sin tener que tocar la tabla
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_horario_unico
        ON horario (clase_id, dia_semana, hora_inicio)
    """)
    # justificaciones: motivo (y opcionalmente archivo adjunto) que una familia da para
    # justificar la falta de un dia completo
    conn.execute("""
        CREATE TABLE IF NOT EXISTS justificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            motivo TEXT NOT NULL,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    # alertas: aviso generado automaticamente cuando termina una clase y el alumno no
    # ha sido detectado; UNIQUE evita duplicar el aviso si se vuelve a comprobar el mismo tramo
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tramo_inicio TEXT NOT NULL,
            asignatura TEXT NOT NULL,
            creado TEXT NOT NULL,
            UNIQUE(persona_id, fecha, tramo_inicio),
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    # padres: cuentas de acceso del portal de familias, cada una ligada a un alumno
    conn.execute("""
        CREATE TABLE IF NOT EXISTS padres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            persona_id INTEGER NOT NULL,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    # migraciones: si la base de datos ya existia de una version anterior del proyecto
    # (sin estas columnas), se anaden ahora sin borrar los datos que ya hubiera
    columnas = [c[1] for c in conn.execute("PRAGMA table_info(personas)")]
    if "clase_id" not in columnas:
        conn.execute("ALTER TABLE personas ADD COLUMN clase_id INTEGER REFERENCES clases(id)")
    if "email_padre" not in columnas:
        conn.execute("ALTER TABLE personas ADD COLUMN email_padre TEXT")
    columnas_justif = [c[1] for c in conn.execute("PRAGMA table_info(justificaciones)")]
    if "archivo" not in columnas_justif:
        conn.execute("ALTER TABLE justificaciones ADD COLUMN archivo TEXT")
    conn.commit()
    asegurar_clase_por_defecto(conn)
    return conn


def asegurar_clase_por_defecto(conn):
    """Si no existe todavia ninguna clase, crea la de partida (NOMBRE_CLASE_DEFECTO) con
    su horario semanal completo. Se llama automaticamente al final de conectar(), asi que
    tanto reconocer.py como app.py (y sus versiones compiladas en .exe) tienen ya una
    clase donde encajar a los alumnos desde el primer arranque, sin ejecutar nada a mano.
    Si ya existe alguna clase (uso normal, dia a dia), no hace nada."""
    if listar_clases(conn):
        return

    crear_clase(conn, NOMBRE_CLASE_DEFECTO, HORA_ENTRADA_DEFECTO)
    clase_id = conn.execute(
        "SELECT id FROM clases WHERE nombre = ?", (NOMBRE_CLASE_DEFECTO,)
    ).fetchone()[0]

    for dia, asignaturas in HORARIO_SEMANAL_DEFECTO.items():
        for (inicio, fin), asignatura in zip(TRAMOS_DEFECTO, asignaturas):
            guardar_horario(conn, clase_id, dia, inicio, fin, asignatura)


def guardar_persona(conn, nombre, encoding):
    """Guarda (o actualiza si el nombre ya existia) el encoding facial de una persona.
    El encoding es un array de numpy; se convierte a bytes (BLOB) para poder guardarlo en SQLite."""
    blob = np.asarray(encoding, dtype=np.float64).tobytes()
    conn.execute(
        "INSERT INTO personas (nombre, encoding) VALUES (?, ?) "
        "ON CONFLICT(nombre) DO UPDATE SET encoding = excluded.encoding",
        (nombre, blob),
    )
    conn.commit()


def obtener_personas(conn):
    """Devuelve lista de (id, nombre, encoding) con encoding como np.array.
    Se usa al arrancar reconocer.py para cargar todas las caras conocidas de una vez."""
    filas = conn.execute("SELECT id, nombre, encoding FROM personas").fetchall()
    return [
        # el BLOB guardado son bytes crudos; frombuffer los reinterpreta como el array original
        (id_, nombre, np.frombuffer(blob, dtype=np.float64))
        for id_, nombre, blob in filas
    ]


def registrar_asistencia(conn, persona_id, fecha_hora, foto):
    """Inserta una fila de asistencia: la camara reconocio a esta persona en este momento."""
    conn.execute(
        "INSERT INTO asistencias (persona_id, fecha_hora, foto) VALUES (?, ?, ?)",
        (persona_id, fecha_hora, foto),
    )
    conn.commit()


def crear_clase(conn, nombre, hora_entrada):
    """hora_entrada en formato 'HH:MM'."""
    conn.execute(
        "INSERT INTO clases (nombre, hora_entrada) VALUES (?, ?) "
        "ON CONFLICT(nombre) DO UPDATE SET hora_entrada = excluded.hora_entrada",
        (nombre, hora_entrada),
    )
    conn.commit()


def asignar_clase(conn, persona_id, clase_id):
    """Mete a una persona en una clase (o la cambia de clase si ya tenia otra)."""
    conn.execute("UPDATE personas SET clase_id = ? WHERE id = ?", (clase_id, persona_id))
    conn.commit()


def listar_clases(conn):
    """Devuelve todas las clases como lista de tuplas (id, nombre, hora_entrada).
    De momento el proyecto solo usa la primera (clases[0]) porque solo hay una clase."""
    return conn.execute("SELECT id, nombre, hora_entrada FROM clases").fetchall()


def guardar_horario(conn, clase_id, dia_semana, hora_inicio, hora_fin, asignatura):
    """Anade un tramo (una hora de una asignatura) al horario semanal de una clase.
    Usa INSERT OR IGNORE: si ese tramo (misma clase/dia/hora) ya existia, no hace nada,
    para poder ejecutar el script de siembra mas de una vez sin duplicar filas."""
    conn.execute(
        "INSERT OR IGNORE INTO horario (clase_id, dia_semana, hora_inicio, hora_fin, asignatura) "
        "VALUES (?, ?, ?, ?, ?)",
        (clase_id, dia_semana, hora_inicio, hora_fin, asignatura),
    )
    conn.commit()


def horario_del_dia(conn, clase_id, dia_semana):
    """Tramos horarios (hora_inicio, hora_fin, asignatura) de una clase para un dia (0=lunes..6=domingo)."""
    return conn.execute(
        "SELECT hora_inicio, hora_fin, asignatura FROM horario "
        "WHERE clase_id = ? AND dia_semana = ? ORDER BY hora_inicio",
        (clase_id, dia_semana),
    ).fetchall()


def asistencia_del_dia(conn, persona_id, fecha):
    """Primera asistencia registrada de una persona en una fecha ('YYYY-MM-DD'), o None."""
    fila = conn.execute(
        "SELECT fecha_hora FROM asistencias "
        "WHERE persona_id = ? AND fecha_hora LIKE ? ORDER BY fecha_hora ASC LIMIT 1",
        (persona_id, f"{fecha}%"),
    ).fetchone()
    return fila[0] if fila else None


def asistencia_en_tramo(conn, persona_id, fecha, hora_inicio, hora_fin):
    """Primera asistencia de una persona ese dia dentro de una franja horaria, o None."""
    fila = conn.execute(
        "SELECT fecha_hora FROM asistencias "
        "WHERE persona_id = ? AND fecha_hora >= ? AND fecha_hora <= ? "
        "ORDER BY fecha_hora ASC LIMIT 1",
        (persona_id, f"{fecha}T{hora_inicio}", f"{fecha}T{hora_fin}"),
    ).fetchone()
    return fila[0] if fila else None


def justificacion_del_dia(conn, persona_id, fecha):
    """Motivo de la justificacion de ese dia (si existe), o None si no se ha justificado."""
    fila = conn.execute(
        "SELECT motivo FROM justificaciones WHERE persona_id = ? AND fecha = ?",
        (persona_id, fecha),
    ).fetchone()
    return fila[0] if fila else None


def justificacion_archivo_del_dia(conn, persona_id, fecha):
    """Nombre del archivo adjunto (justificante medico, etc.) de ese dia, o None si no hay."""
    fila = conn.execute(
        "SELECT archivo FROM justificaciones WHERE persona_id = ? AND fecha = ?",
        (persona_id, fecha),
    ).fetchone()
    return fila[0] if fila and fila[0] else None


def justificar_falta(conn, persona_id, fecha, motivo, archivo=None):
    """Registra la justificacion de un dia completo (cubre todas las asignaturas de ese dia)."""
    conn.execute(
        "INSERT INTO justificaciones (persona_id, fecha, motivo, archivo) VALUES (?, ?, ?, ?)",
        (persona_id, fecha, motivo, archivo),
    )
    conn.commit()


def generar_alerta(conn, persona_id, fecha, tramo_inicio, asignatura, creado):
    """Registra una alerta de falta (no hace nada si ya existe una para ese alumno/dia/tramo)."""
    conn.execute(
        "INSERT OR IGNORE INTO alertas (persona_id, fecha, tramo_inicio, asignatura, creado) "
        "VALUES (?, ?, ?, ?, ?)",
        (persona_id, fecha, tramo_inicio, asignatura, creado),
    )
    conn.commit()


def listar_alertas_clase(conn, clase_id, solo_pendientes=False):
    """Alertas de una clase (mas recientes primero), con nombre del alumno, si ya esta
    justificada y el archivo adjunto (si tiene). Las dos subconsultas EXISTS/SELECT
    comprueban, para cada alerta, si esa fecha+persona tiene ya una fila en
    justificaciones (osea si la falta ya se justifico)."""
    filas = conn.execute("""
        SELECT a.id, p.nombre, a.persona_id, a.fecha, a.asignatura, a.creado,
               EXISTS(
                   SELECT 1 FROM justificaciones j
                   WHERE j.persona_id = a.persona_id AND j.fecha = a.fecha
               ) AS justificada,
               (
                   SELECT j.archivo FROM justificaciones j
                   WHERE j.persona_id = a.persona_id AND j.fecha = a.fecha
               ) AS archivo
        FROM alertas a
        JOIN personas p ON p.id = a.persona_id
        WHERE p.clase_id = ?
        ORDER BY a.fecha DESC, a.tramo_inicio DESC
    """, (clase_id,)).fetchall()
    if solo_pendientes:
        filas = [f for f in filas if not f[6]]  # f[6] es la columna "justificada"
    return filas


def listar_alertas_persona(conn, persona_id):
    """Todas las alertas de un alumno (usado en el portal de padres)."""
    return conn.execute("""
        SELECT a.fecha, a.asignatura, a.creado,
               EXISTS(
                   SELECT 1 FROM justificaciones j
                   WHERE j.persona_id = a.persona_id AND j.fecha = a.fecha
               ) AS justificada
        FROM alertas a
        WHERE a.persona_id = ?
        ORDER BY a.fecha DESC, a.tramo_inicio DESC
    """, (persona_id,)).fetchall()


def crear_padre(conn, email, password_hash, persona_id):
    """Crea una cuenta de familia. password_hash ya viene cifrado (nunca se guarda en texto plano)."""
    conn.execute(
        "INSERT INTO padres (email, password_hash, persona_id) VALUES (?, ?, ?)",
        (email, password_hash, persona_id),
    )
    conn.commit()


def obtener_padre_por_email(conn, email):
    """Devuelve (id, email, password_hash, persona_id) o None."""
    return conn.execute(
        "SELECT id, email, password_hash, persona_id FROM padres WHERE email = ?", (email,)
    ).fetchone()
