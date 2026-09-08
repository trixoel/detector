# Aplicacion web (Flask) del proyecto. Tiene dos partes independientes:
#  - el panel del profesor/centro: / , /horario, /alumnado, /alertas (sin login todavia)
#  - el portal de familias: /padres/* (con cuenta y login propios, cada familia solo ve a su hijo/a)
import os
import uuid
from datetime import datetime, date, timedelta
from functools import wraps
from collections import OrderedDict

from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import db

# template_folder explicito: en modo empaquetado (.exe), Flask no adivinaria solo donde
# quedaron las plantillas HTML dentro del paquete; db.app_dir() apunta siempre a la
# carpeta del programa (ver comentario de esa funcion en db.py)
app = Flask(__name__, template_folder=os.path.join(db.app_dir(), "templates"))
app.secret_key = "clave-de-desarrollo-cambiar-en-produccion"  # firma las cookies de sesion; cambiar en produccion

DIAS_A_REVISAR_PADRES = 14  # cuantos dias hacia atras mira el portal de padres
MARGEN_RETRASO_MIN = 5  # minutos de cortesia antes de marcar retraso
NOMBRES_DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]
CARPETA_JUSTIFICANTES = os.path.join(db.base_dir(), "justificantes")
EXTENSIONES_PERMITIDAS = {"pdf", "jpg", "jpeg", "png"}

os.makedirs(CARPETA_JUSTIFICANTES, exist_ok=True)


def login_requerido(vista):
    """Decorador para las rutas del portal de padres: si no hay sesion iniciada,
    redirige al login en vez de ejecutar la vista."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "persona_id" not in session:
            return redirect(url_for("padres_login"))
        return vista(*args, **kwargs)
    return envoltura


def sincronizar_alertas(conn, clase_id, fecha):
    """Genera una alerta por cada alumno/asignatura de ese dia cuyo periodo ya termino sin
    asistencia. Se llama al cargar las paginas (no hay un proceso en segundo plano aparte),
    asi que cada visita a la web "pone al dia" las alertas que falten por generar."""
    dia_semana = datetime.strptime(fecha, "%Y-%m-%d").weekday()
    tramos = db.horario_del_dia(conn, clase_id, dia_semana)
    if not tramos:
        return  # fin de semana o dia sin horario: nada que comprobar

    es_hoy = fecha == date.today().isoformat()
    ahora = datetime.now().strftime("%H:%M")

    personas = conn.execute("SELECT id FROM personas WHERE clase_id = ?", (clase_id,)).fetchall()
    for (persona_id,) in personas:
        for inicio, fin, asignatura in tramos:
            if asignatura == "RECREO":
                continue
            if es_hoy and fin > ahora:
                continue  # el periodo aun no ha terminado, no se puede saber si faltara
            if db.asistencia_en_tramo(conn, persona_id, fecha, inicio, fin):
                continue  # asistio, no hay falta que avisar
            # INSERT OR IGNORE en generar_alerta evita duplicar la alerta si esto se
            # vuelve a ejecutar para el mismo alumno/dia/tramo
            db.generar_alerta(conn, persona_id, fecha, inicio, asignatura, datetime.now().isoformat())


@app.context_processor
def inyectar_nav():
    """Se ejecuta antes de renderizar CUALQUIER plantilla; anade el contador de alertas
    pendientes que se ve en el sidebar, sin tener que pasarlo a mano en cada ruta."""
    conn = db.conectar()
    clases = db.listar_clases(conn)
    total_pendientes = 0
    if clases:
        total_pendientes = len(db.listar_alertas_clase(conn, clases[0][0], solo_pendientes=True))
    return {"nav_alertas_pendientes": total_pendientes}


@app.route("/")
def index():
    """Vista principal del profesor: asistencia de una asignatura concreta en un dia
    concreto (por defecto, hoy y la primera asignatura del dia)."""
    fecha = request.args.get("fecha", date.today().isoformat())
    conn = db.conectar()

    dia_semana = datetime.strptime(fecha, "%Y-%m-%d").weekday()  # 0=lunes .. 6=domingo

    # calcula el lunes de la semana que se esta viendo, para poder ofrecer las
    # pestanas Lunes-Viernes con la fecha exacta de cada una
    lunes_semana = datetime.strptime(fecha, "%Y-%m-%d").date() - timedelta(days=dia_semana)
    dias_semana = [
        {"nombre": nombre, "fecha": (lunes_semana + timedelta(days=i)).isoformat(), "activo": i == dia_semana}
        for i, nombre in enumerate(NOMBRES_DIAS)
    ]

    clases = []
    for clase_id, nombre_clase, _ in db.listar_clases(conn):
        sincronizar_alertas(conn, clase_id, fecha)  # pone al dia las alertas de este dia antes de mostrar nada

        tramos = db.horario_del_dia(conn, clase_id, dia_semana)

        # tramo seleccionado: el que viene en ?hora= (al hacer clic en una asignatura
        # del horario), o si no se ha elegido ninguno, el primero que no sea recreo.
        # tramos es una lista de tuplas (hora_inicio, hora_fin, asignatura) ya ordenada
        # por hora, asi que el primer "break" que se ejecute deja el tramo correcto
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

        # se calcula el estado (a_tiempo/retraso/falta/justificada) de cada alumno uno
        # a uno; el resultado final es la lista que pinta la tabla en index.html
        alumnos = []
        for persona_id, nombre in personas:
            motivo = db.justificacion_del_dia(conn, persona_id, fecha)

            if tramo_activo:
                inicio, fin, _ = tramo_activo
                # busca si la camara detecto a esta persona dentro de la franja horaria del tramo
                fecha_hora = db.asistencia_en_tramo(conn, persona_id, fecha, inicio, fin)
            else:
                fecha_hora = None

            if fecha_hora:
                hora_llegada = fecha_hora.split("T")[1][:5]  # de "2026-...T08:20:00" nos quedamos con "08:20"
                # se da un margen de cortesia (MARGEN_RETRASO_MIN) antes de considerar retraso
                limite = (datetime.strptime(inicio, "%H:%M") + timedelta(minutes=MARGEN_RETRASO_MIN)).strftime("%H:%M") \
                    if tramo_activo else None
                estado = "retraso" if limite and hora_llegada > limite else "a_tiempo"
            elif motivo:
                # no hay asistencia mas ya se justifico el dia entero
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

        # se guarda ya en el formato que espera la plantilla (diccionarios en vez de
        # tuplas), para no tener que hacer logica dentro del HTML
        clases.append({
            "id": clase_id,
            "nombre": nombre_clase,
            "tramos": [{"inicio": i, "fin": f, "asignatura": a} for i, f, a in tramos],
            "tramo_activo": tramo_activo[0] if tramo_activo else None,  # solo la hora de inicio, para comparar en el HTML
            "asignatura_activa": tramo_activo[2] if tramo_activo else None,  # el nombre, para el texto "Mostrando asistencia de..."
            "alumnos": alumnos,
        })

    return render_template(
        "index.html", clases=clases, fecha=fecha, hoy=date.today().isoformat(),
        dias_semana=dias_semana, seccion="asistencia",
    )


@app.route("/horario")
def horario():
    """Horario semanal completo en forma de cuadricula (filas=horas, columnas=dias)."""
    conn = db.conectar()
    tablas = []
    for clase_id, nombre_clase, _ in db.listar_clases(conn):
        # dias[0] = tramos del lunes, dias[1] = martes, ... cada uno es una lista de
        # (hora_inicio, hora_fin, asignatura) ya ordenada por hora
        dias = [db.horario_del_dia(conn, clase_id, d) for d in range(5)]  # lunes(0) .. viernes(4)
        # se usa como referencia el dia con mas tramos, por si algun dia tuviera menos horas
        referencia = max(dias, key=len)

        # se construye una fila por cada tramo horario de la "referencia"; para cada
        # fila, se mira que asignatura hay ese mismo hueco (posicion i) en cada dia
        filas = []
        for i, (inicio, fin, _) in enumerate(referencia):
            filas.append({
                "inicio": inicio,
                "fin": fin,
                # dias[d][i][2] es la asignatura del dia d en la posicion i; si ese dia
                # no llega a tener tantos tramos, se deja vacio (index fuera de rango)
                "dias": [dias[d][i][2] if i < len(dias[d]) else "" for d in range(5)],
            })

        tablas.append({"nombre": nombre_clase, "filas": filas})

    return render_template("horario.html", tablas=tablas, seccion="horario")


@app.route("/alumnado")
def alumnado():
    """Listado de alumnos por clase: si tienen cuenta de familia y cuantas faltas
    sin justificar acumulan."""
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
            # cada "a" es una tupla (fecha, asignatura, creado, justificada); a[3] es
            # justificada, asi que "not a[3]" filtra las alertas que siguen sin justificar
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
    """Registro (log) de todas las alertas de falta generadas, con opcion de ver solo
    las pendientes de justificar."""
    conn = db.conectar()
    solo_pendientes = request.args.get("pendientes") == "1"

    clases = db.listar_clases(conn)
    filas = []
    if clases:
        # sincronizar los ultimos dias por si aun no se ha visitado / (que es donde
        # normalmente se generan las alertas del dia)
        for i in range(3):
            fecha = (date.today() - timedelta(days=i)).isoformat()
            sincronizar_alertas(conn, clases[0][0], fecha)
        filas = db.listar_alertas_clase(conn, clases[0][0], solo_pendientes=solo_pendientes)

    # cada fila de la base de datos es una tupla larga (id, nombre, persona_id, fecha,
    # asignatura, creado, justificada, archivo); aqui se convierte en un diccionario
    # con solo los campos que necesita la plantilla, y "creado" se recorta/formatea
    # de "2026-...T15:38:43.xxxxx" a "2026-... 15:38" para que se lea mejor
    alertas_vista = [
        {
            "nombre": nombre, "fecha": fecha, "asignatura": asignatura,
            "creado": creado[:16].replace("T", " "), "justificada": justificada, "archivo": archivo,
        }
        for (_, nombre, _, fecha, asignatura, creado, justificada, archivo) in filas
    ]

    return render_template("alertas.html", alertas=alertas_vista, solo_pendientes=solo_pendientes, seccion="alertas")


@app.route("/alertas/justificante/<path:nombre_archivo>")
def descargar_justificante_profesor(nombre_archivo):
    # el panel del profesor no tiene login propio todavia, igual que el resto de /alertas
    return send_from_directory(CARPETA_JUSTIFICANTES, nombre_archivo)


@app.route("/padres/login", methods=["GET", "POST"])
def padres_login():
    """Login del portal de familias. Guarda el id del alumno (no el del padre) en la
    sesion: es lo que necesitan el resto de rutas para saber de quien mostrar los datos."""
    error = None
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = db.conectar()
        padre = db.obtener_padre_por_email(conn, email)

        # check_password_hash compara la contraseña escrita contra el hash guardado
        # (nunca se guarda ni se compara la contraseña en texto plano)
        if padre and check_password_hash(padre[2], password):
            session["persona_id"] = padre[3]
            return redirect(url_for("padres_dashboard"))
        error = "Email o contraseña incorrectos"

    return render_template("padres_login.html", error=error)


@app.route("/padres/registro", methods=["GET", "POST"])
def padres_registro():
    """Alta de una cuenta de familia, ligada a un alumno ya existente en el sistema."""
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
            # generate_password_hash cifra la contraseña antes de guardarla
            db.crear_padre(conn, email, generate_password_hash(password), persona_id)
            session["persona_id"] = int(persona_id)
            return redirect(url_for("padres_dashboard"))

    return render_template("padres_registro.html", error=error, personas=personas)


@app.route("/padres/logout")
def padres_logout():
    """Borra el id de persona de la sesion: eso basta para que login_requerido
    vuelva a pedir iniciar sesion en cualquier ruta protegida."""
    session.pop("persona_id", None)
    return redirect(url_for("padres_login"))


@app.route("/padres")
@login_requerido
def padres_dashboard():
    """Vista principal de la familia: faltas de los ultimos dias, agrupadas por dia,
    con opcion de justificarlas."""
    persona_id = session["persona_id"]
    conn = db.conectar()

    fila = conn.execute("SELECT nombre, clase_id FROM personas WHERE id = ?", (persona_id,)).fetchone()
    nombre, clase_id = fila

    if clase_id:
        # se comprueban los ultimos DIAS_A_REVISAR_PADRES dias uno a uno, por si el
        # profesor no ha visitado la web esos dias y las alertas no se generaron aun
        for i in range(DIAS_A_REVISAR_PADRES):
            sincronizar_alertas(conn, clase_id, (date.today() - timedelta(days=i)).isoformat())

    # listar_alertas_persona devuelve una fila POR ASIGNATURA (si un dia entero falta,
    # salen 6-7 filas, una por cada clase de ese dia). Aqui se agrupan en una sola
    # tarjeta por dia, juntando los nombres de las asignaturas en una lista.
    # OrderedDict porque las filas ya vienen ordenadas por fecha y queremos conservar ese orden
    por_dia = OrderedDict()
    for fecha, asignatura, _, justificada in db.listar_alertas_persona(conn, persona_id):
        if fecha not in por_dia:
            # la primera vez que aparece esta fecha se crea la tarjeta (y se busca el
            # archivo adjunto, si lo hay); las siguientes veces solo se anade la asignatura
            archivo = db.justificacion_archivo_del_dia(conn, persona_id, fecha) if justificada else None
            por_dia[fecha] = {"fecha": fecha, "asignaturas": [], "justificada": justificada, "archivo": archivo}
        por_dia[fecha]["asignaturas"].append(asignatura)

    faltas = list(por_dia.values())  # de diccionario {fecha: tarjeta} a lista de tarjetas, para la plantilla

    return render_template("padres_dashboard.html", nombre=nombre, faltas=faltas, seccion="faltas")


@app.route("/padres/alumno")
@login_requerido
def padres_alumno():
    """Ficha del alumno para la familia: datos, resumen de asistencia y su horario."""
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

    # aqui solo interesa CONTAR dias, no el detalle de asignaturas, asi que basta con
    # quedarse una vez por fecha (setdefault no sobreescribe si la fecha ya estaba)
    grupos = OrderedDict()
    for fecha, _, _, justificada in db.listar_alertas_persona(conn, persona_id):
        grupos.setdefault(fecha, justificada)
    total_faltas = len(grupos)
    justificadas = sum(1 for j in grupos.values() if j)  # cuenta cuantos valores son True

    return render_template(
        "padres_alumno.html", nombre=nombre, clase_nombre=clase_nombre, horario_filas=horario_filas,
        dias_revisados=DIAS_A_REVISAR_PADRES, total_faltas=total_faltas, justificadas=justificadas,
        pendientes=total_faltas - justificadas, seccion="alumno",
    )


@app.route("/padres/justificar", methods=["POST"])
@login_requerido
def justificar():
    """Recibe el formulario de justificar una falta, con archivo adjunto opcional
    (justificante medico, etc.)."""
    persona_id = session["persona_id"]
    fecha = request.form["fecha"]
    motivo = request.form["motivo"]

    nombre_archivo = None
    archivo = request.files.get("justificante")  # None si el campo del formulario venia vacio
    if archivo and archivo.filename:
        extension = archivo.filename.rsplit(".", 1)[-1].lower()
        if extension in EXTENSIONES_PERMITIDAS:  # si no es pdf/jpg/jpeg/png, se ignora el archivo
            # el nombre incluye persona_id (para saber de quien es al servirlo) y un
            # trozo aleatorio (uuid) para que dos archivos con el mismo nombre no se pisen
            nombre_archivo = f"{persona_id}_{fecha}_{uuid.uuid4().hex[:8]}_{secure_filename(archivo.filename)}"
            archivo.save(os.path.join(CARPETA_JUSTIFICANTES, nombre_archivo))

    conn = db.conectar()
    db.justificar_falta(conn, persona_id, fecha, motivo, nombre_archivo)

    return redirect(url_for("padres_dashboard"))


@app.route("/justificantes/<path:nombre_archivo>")
@login_requerido
def servir_justificante(nombre_archivo):
    """Descarga de un justificante desde el portal de padres. Solo se sirve si el
    archivo pertenece al alumno de la sesion (comprobado por el prefijo del nombre),
    para que una familia no pueda ver el justificante de otro alumno."""
    if not nombre_archivo.startswith(f"{session['persona_id']}_"):
        return "No autorizado", 403
    return send_from_directory(CARPETA_JUSTIFICANTES, nombre_archivo)


if __name__ == "__main__":
    # debug=True: recarga el servidor solo al guardar cambios en el codigo, y muestra
    # el traceback completo en el navegador si algo falla (solo para desarrollo)
    app.run(debug=True)
