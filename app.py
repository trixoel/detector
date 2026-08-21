import os
import uuid
from datetime import datetime, date, timedelta
from functools import wraps
from collections import OrderedDict

from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import db

app = Flask(__name__)
app.secret_key = "clave-de-desarrollo-cambiar-en-produccion"

DIAS_A_REVISAR_PADRES = 14  # cuantos dias hacia atras mira el portal de padres
MARGEN_RETRASO_MIN = 5  # minutos de cortesia antes de marcar retraso
NOMBRES_DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]
CARPETA_JUSTIFICANTES = "justificantes"
EXTENSIONES_PERMITIDAS = {"pdf", "jpg", "jpeg", "png"}

os.makedirs(CARPETA_JUSTIFICANTES, exist_ok=True)


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "persona_id" not in session:
            return redirect(url_for("padres_login"))
        return vista(*args, **kwargs)
    return envoltura


def sincronizar_alertas(conn, clase_id, fecha):
    """Genera una alerta por cada alumno/asignatura de ese dia cuyo periodo ya termino sin asistencia."""
    dia_semana = datetime.strptime(fecha, "%Y-%m-%d").weekday()
    tramos = db.horario_del_dia(conn, clase_id, dia_semana)
    if not tramos:
        return

    es_hoy = fecha == date.today().isoformat()
    ahora = datetime.now().strftime("%H:%M")

    personas = conn.execute("SELECT id FROM personas WHERE clase_id = ?", (clase_id,)).fetchall()
    for (persona_id,) in personas:
        for inicio, fin, asignatura in tramos:
            if asignatura == "RECREO":
                continue
            if es_hoy and fin > ahora:
                continue  # el periodo aun no ha terminado
            if db.asistencia_en_tramo(conn, persona_id, fecha, inicio, fin):
                continue  # asistio, no hay falta que avisar
            db.generar_alerta(conn, persona_id, fecha, inicio, asignatura, datetime.now().isoformat())


@app.context_processor
def inyectar_nav():
    conn = db.conectar()
    clases = db.listar_clases(conn)
    total_pendientes = 0
    if clases:
        total_pendientes = len(db.listar_alertas_clase(conn, clases[0][0], solo_pendientes=True))
    return {"nav_alertas_pendientes": total_pendientes}


@app.route("/")
def index():
    fecha = request.args.get("fecha", date.today().isoformat())
    conn = db.conectar()

    dia_semana = datetime.strptime(fecha, "%Y-%m-%d").weekday()  # 0=lunes .. 6=domingo

    lunes_semana = datetime.strptime(fecha, "%Y-%m-%d").date() - timedelta(days=dia_semana)
    dias_semana = [
        {"nombre": nombre, "fecha": (lunes_semana + timedelta(days=i)).isoformat(), "activo": i == dia_semana}
        for i, nombre in enumerate(NOMBRES_DIAS)
    ]

    clases = []
    for clase_id, nombre_clase, _ in db.listar_clases(conn):
        sincronizar_alertas(conn, clase_id, fecha)

        tramos = db.horario_del_dia(conn, clase_id, dia_semana)

        # tramo seleccionado: el que viene en ?hora=, o el primero que no sea recreo
        hora_seleccionada = request.args.get("hora")
        tramo_activo = None
        for inicio, fin, asignatura in tramos:
            if hora_seleccionada:
                if inicio == hora_seleccionada:
                    tramo_activo = (inicio, fin, asignatura)
                    break
            elif asignatura != "RECREO":
                tramo_activo = (inicio, fin, asignatura)
                break

        personas = conn.execute(
            "SELECT id, nombre FROM personas WHERE clase_id = ?", (clase_id,)
        ).fetchall()

        alumnos = []
        for persona_id, nombre in personas:
            motivo = db.justificacion_del_dia(conn, persona_id, fecha)

            if tramo_activo:
                inicio, fin, _ = tramo_activo
                fecha_hora = db.asistencia_en_tramo(conn, persona_id, fecha, inicio, fin)
            else:
                fecha_hora = None

            if fecha_hora:
                hora_llegada = fecha_hora.split("T")[1][:5]
                limite = (datetime.strptime(inicio, "%H:%M") + timedelta(minutes=MARGEN_RETRASO_MIN)).strftime("%H:%M") \
                    if tramo_activo else None
                estado = "retraso" if limite and hora_llegada > limite else "a_tiempo"
            elif motivo:
                hora_llegada = None
                estado = "justificada"
            else:
                hora_llegada = None
                estado = "falta"

            alumnos.append({
                "id": persona_id,
                "nombre": nombre,
                "hora_llegada": hora_llegada,
                "estado": estado,
                "motivo": motivo,
            })

        clases.append({
            "id": clase_id,
            "nombre": nombre_clase,
            "tramos": [{"inicio": i, "fin": f, "asignatura": a} for i, f, a in tramos],
            "tramo_activo": tramo_activo[0] if tramo_activo else None,
            "asignatura_activa": tramo_activo[2] if tramo_activo else None,
            "alumnos": alumnos,
        })

    return render_template(
        "index.html", clases=clases, fecha=fecha, hoy=date.today().isoformat(),
        dias_semana=dias_semana, seccion="asistencia",
    )


@app.route("/horario")
def horario():
    conn = db.conectar()
    tablas = []
    for clase_id, nombre_clase, _ in db.listar_clases(conn):
        dias = [db.horario_del_dia(conn, clase_id, d) for d in range(5)]
        referencia = max(dias, key=len)

        filas = []
        for i, (inicio, fin, _) in enumerate(referencia):
            filas.append({
                "inicio": inicio,
                "fin": fin,
                "dias": [dias[d][i][2] if i < len(dias[d]) else "" for d in range(5)],
            })

        tablas.append({"nombre": nombre_clase, "filas": filas})

    return render_template("horario.html", tablas=tablas, seccion="horario")


@app.route("/alumnado")
def alumnado():
    conn = db.conectar()
    clases = []
    for clase_id, nombre_clase, _ in db.listar_clases(conn):
        filas = conn.execute("""
            SELECT p.id, p.nombre, pa.email
            FROM personas p
            LEFT JOIN padres pa ON pa.persona_id = p.id
            WHERE p.clase_id = ?
            ORDER BY p.nombre
        """, (clase_id,)).fetchall()

        alumnos = []
        for persona_id, nombre, email_padre in filas:
            pendientes = [
                a for a in db.listar_alertas_persona(conn, persona_id) if not a[3]
            ]
            alumnos.append({
                "nombre": nombre,
                "email_padre": email_padre,
                "faltas_pendientes": len(pendientes),
            })

        clases.append({"nombre": nombre_clase, "alumnos": alumnos})

    return render_template("alumnado.html", clases=clases, seccion="alumnado")


@app.route("/alertas")
def alertas():
    conn = db.conectar()
    solo_pendientes = request.args.get("pendientes") == "1"

    clases = db.listar_clases(conn)
    filas = []
    if clases:
        # sincronizar los ultimos dias por si aun no se ha visitado /
        for i in range(3):
            fecha = (date.today() - timedelta(days=i)).isoformat()
            sincronizar_alertas(conn, clases[0][0], fecha)
        filas = db.listar_alertas_clase(conn, clases[0][0], solo_pendientes=solo_pendientes)

    alertas_vista = [
        {"nombre": nombre, "fecha": fecha, "asignatura": asignatura, "creado": creado[:16].replace("T", " "), "justificada": justificada}
        for (_, nombre, _, fecha, asignatura, creado, justificada) in filas
    ]

    return render_template("alertas.html", alertas=alertas_vista, solo_pendientes=solo_pendientes, seccion="alertas")


@app.route("/padres/login", methods=["GET", "POST"])
def padres_login():
    error = None
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = db.conectar()
        padre = db.obtener_padre_por_email(conn, email)

        if padre and check_password_hash(padre[2], password):
            session["persona_id"] = padre[3]
            return redirect(url_for("padres_dashboard"))
        error = "Email o contraseña incorrectos"

    return render_template("padres_login.html", error=error)


@app.route("/padres/registro", methods=["GET", "POST"])
def padres_registro():
    error = None
    conn = db.conectar()
    personas = conn.execute("SELECT id, nombre FROM personas").fetchall()

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        persona_id = request.form["persona_id"]

        if db.obtener_padre_por_email(conn, email):
            error = "Ese email ya tiene una cuenta"
        else:
            db.crear_padre(conn, email, generate_password_hash(password), persona_id)
            session["persona_id"] = int(persona_id)
            return redirect(url_for("padres_dashboard"))

    return render_template("padres_registro.html", error=error, personas=personas)


@app.route("/padres/logout")
def padres_logout():
    session.pop("persona_id", None)
    return redirect(url_for("padres_login"))


@app.route("/padres")
@login_requerido
def padres_dashboard():
    persona_id = session["persona_id"]
    conn = db.conectar()

    fila = conn.execute("SELECT nombre, clase_id FROM personas WHERE id = ?", (persona_id,)).fetchone()
    nombre, clase_id = fila

    if clase_id:
        for i in range(DIAS_A_REVISAR_PADRES):
            sincronizar_alertas(conn, clase_id, (date.today() - timedelta(days=i)).isoformat())

    # agrupar las alertas (una por asignatura) en una tarjeta por dia
    por_dia = OrderedDict()
    for fecha, asignatura, _, justificada in db.listar_alertas_persona(conn, persona_id):
        if fecha not in por_dia:
            archivo = db.justificacion_archivo_del_dia(conn, persona_id, fecha) if justificada else None
            por_dia[fecha] = {"fecha": fecha, "asignaturas": [], "justificada": justificada, "archivo": archivo}
        por_dia[fecha]["asignaturas"].append(asignatura)

    faltas = list(por_dia.values())

    return render_template("padres_dashboard.html", nombre=nombre, faltas=faltas, seccion="faltas")


@app.route("/padres/alumno")
@login_requerido
def padres_alumno():
    persona_id = session["persona_id"]
    conn = db.conectar()

    nombre, clase_id = conn.execute(
        "SELECT nombre, clase_id FROM personas WHERE id = ?", (persona_id,)
    ).fetchone()

    clase_nombre = None
    horario_filas = []
    if clase_id:
        clase_nombre = conn.execute("SELECT nombre FROM clases WHERE id = ?", (clase_id,)).fetchone()[0]
        dias = [db.horario_del_dia(conn, clase_id, d) for d in range(5)]
        referencia = max(dias, key=len)
        for i, (inicio, fin, _) in enumerate(referencia):
            horario_filas.append({
                "inicio": inicio, "fin": fin,
                "dias": [dias[d][i][2] if i < len(dias[d]) else "" for d in range(5)],
            })

    grupos = OrderedDict()
    for fecha, _, _, justificada in db.listar_alertas_persona(conn, persona_id):
        grupos.setdefault(fecha, justificada)
    total_faltas = len(grupos)
    justificadas = sum(1 for j in grupos.values() if j)

    return render_template(
        "padres_alumno.html", nombre=nombre, clase_nombre=clase_nombre, horario_filas=horario_filas,
        dias_revisados=DIAS_A_REVISAR_PADRES, total_faltas=total_faltas, justificadas=justificadas,
        pendientes=total_faltas - justificadas, seccion="alumno",
    )


@app.route("/padres/justificar", methods=["POST"])
@login_requerido
def justificar():
    persona_id = session["persona_id"]
    fecha = request.form["fecha"]
    motivo = request.form["motivo"]

    nombre_archivo = None
    archivo = request.files.get("justificante")
    if archivo and archivo.filename:
        extension = archivo.filename.rsplit(".", 1)[-1].lower()
        if extension in EXTENSIONES_PERMITIDAS:
            nombre_archivo = f"{persona_id}_{fecha}_{uuid.uuid4().hex[:8]}_{secure_filename(archivo.filename)}"
            archivo.save(os.path.join(CARPETA_JUSTIFICANTES, nombre_archivo))

    conn = db.conectar()
    db.justificar_falta(conn, persona_id, fecha, motivo, nombre_archivo)

    return redirect(url_for("padres_dashboard"))


@app.route("/justificantes/<path:nombre_archivo>")
@login_requerido
def servir_justificante(nombre_archivo):
    # cada archivo empieza por el id de la persona a la que pertenece; solo su propia familia puede verlo
    if not nombre_archivo.startswith(f"{session['persona_id']}_"):
        return "No autorizado", 403
    return send_from_directory(CARPETA_JUSTIFICANTES, nombre_archivo)


if __name__ == "__main__":
    app.run(debug=True)
