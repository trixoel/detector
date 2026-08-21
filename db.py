import sqlite3
import numpy as np

DB_PATH = "asistencia.db"


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            encoding BLOB NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asistencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            fecha_hora TEXT NOT NULL,
            foto TEXT,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            hora_entrada TEXT NOT NULL
        )
    """)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS justificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            motivo TEXT NOT NULL,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS padres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            persona_id INTEGER NOT NULL,
            FOREIGN KEY (persona_id) REFERENCES personas(id)
        )
    """)
    # migraciones sobre bases de datos ya existentes
    columnas = [c[1] for c in conn.execute("PRAGMA table_info(personas)")]
    if "clase_id" not in columnas:
        conn.execute("ALTER TABLE personas ADD COLUMN clase_id INTEGER REFERENCES clases(id)")
    if "email_padre" not in columnas:
        conn.execute("ALTER TABLE personas ADD COLUMN email_padre TEXT")
    columnas_justif = [c[1] for c in conn.execute("PRAGMA table_info(justificaciones)")]
    if "archivo" not in columnas_justif:
        conn.execute("ALTER TABLE justificaciones ADD COLUMN archivo TEXT")
    conn.commit()
    return conn


def guardar_persona(conn, nombre, encoding):
    blob = np.asarray(encoding, dtype=np.float64).tobytes()
    conn.execute(
        "INSERT INTO personas (nombre, encoding) VALUES (?, ?) "
        "ON CONFLICT(nombre) DO UPDATE SET encoding = excluded.encoding",
        (nombre, blob),
    )
    conn.commit()


def obtener_personas(conn):
    """Devuelve lista de (id, nombre, encoding) con encoding como np.array."""
    filas = conn.execute("SELECT id, nombre, encoding FROM personas").fetchall()
    return [
        (id_, nombre, np.frombuffer(blob, dtype=np.float64))
        for id_, nombre, blob in filas
    ]


def registrar_asistencia(conn, persona_id, fecha_hora, foto):
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
    conn.execute("UPDATE personas SET clase_id = ? WHERE id = ?", (clase_id, persona_id))
    conn.commit()


def listar_clases(conn):
    return conn.execute("SELECT id, nombre, hora_entrada FROM clases").fetchall()


def guardar_horario(conn, clase_id, dia_semana, hora_inicio, hora_fin, asignatura):
    conn.execute(
        "INSERT INTO horario (clase_id, dia_semana, hora_inicio, hora_fin, asignatura) "
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
    fila = conn.execute(
        "SELECT motivo FROM justificaciones WHERE persona_id = ? AND fecha = ?",
        (persona_id, fecha),
    ).fetchone()
    return fila[0] if fila else None


def justificacion_archivo_del_dia(conn, persona_id, fecha):
    fila = conn.execute(
        "SELECT archivo FROM justificaciones WHERE persona_id = ? AND fecha = ?",
        (persona_id, fecha),
    ).fetchone()
    return fila[0] if fila and fila[0] else None


def justificar_falta(conn, persona_id, fecha, motivo, archivo=None):
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
    """Alertas de una clase (mas recientes primero), con nombre del alumno y si ya esta justificada."""
    filas = conn.execute("""
        SELECT a.id, p.nombre, a.persona_id, a.fecha, a.asignatura, a.creado,
               EXISTS(
                   SELECT 1 FROM justificaciones j
                   WHERE j.persona_id = a.persona_id AND j.fecha = a.fecha
               ) AS justificada
        FROM alertas a
        JOIN personas p ON p.id = a.persona_id
        WHERE p.clase_id = ?
        ORDER BY a.fecha DESC, a.tramo_inicio DESC
    """, (clase_id,)).fetchall()
    if solo_pendientes:
        filas = [f for f in filas if not f[6]]
    return filas


def listar_alertas_persona(conn, persona_id):
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
