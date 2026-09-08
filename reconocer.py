# Script principal: abre la camara en directo, reconoce caras conocidas y registra su
# asistencia en la base de datos. Tambien permite dar de alta gente nueva sobre la marcha (tecla 'r').
import cv2
import face_recognition
import os
import time
from datetime import datetime

import db

TOLERANCIA = 0.6  # distancia maxima entre encodings para considerar que es la misma persona; menor = mas estricto
INTERVALO_MISMA_PERSONA = 30  # segundos entre registros de la misma persona (evita llenar la tabla cada frame)
CARPETA_CAPTURAS = os.path.join(db.base_dir(), "caras_detectadas")

os.makedirs(CARPETA_CAPTURAS, exist_ok=True)

conn = db.conectar()
# se cargan todas las caras conocidas UNA vez al arrancar; comparar contra listas en
# memoria es mucho mas rapido que consultar la base de datos en cada frame
personas = db.obtener_personas(conn)
if not personas:
    print("No hay personas registradas. Usa registrar_persona.py primero.")

# los alumnos que se registren en directo (tecla 'r') se meten automaticamente en esta clase,
# ya que de momento solo existe una
clases = db.listar_clases(conn)
clase_por_defecto = clases[0][0] if clases else None
if clase_por_defecto is None:
    print("Aviso: no hay ninguna clase creada, los nuevos registros no se veran en la web hasta crear una.")

# tres listas paralelas (misma posicion = misma persona) para poder comparar con
# face_recognition.face_distance, que trabaja con listas de encodings
nombres = [p[1] for p in personas]
ids = [p[0] for p in personas]
encodings_conocidos = [p[2] for p in personas]

ultimo_registro = {}  # persona_id -> timestamp del ultimo registro

# estado del "modo alta": mientras esta activo, las teclas se usan para escribir el
# nombre en pantalla en vez de para las acciones normales (registrar, salir, etc.)
modo_registro = False
texto_nombre = ""
encoding_pendiente = None

# CAP_DSHOW: backend de camara de Windows; sin esto, algunas camaras fallan al abrir con OpenCV
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

# deteccion+reconocimiento es lo mas lento de todo el bucle; para no ir con lag se hace
# a menor resolucion (ESCALA) y no en todos los frames (solo 1 de cada N)
ESCALA = 0.5
PROCESAR_CADA_N_FRAMES = 3  # detectar y reconocer 1 de cada N frames; el resto reutiliza lo ultimo detectado
contador_frames = 0
ubicaciones = []
encodings = []

while True:
    ret, frame = cap.read()
    if not ret:
        break

    contador_frames += 1

    if contador_frames % PROCESAR_CADA_N_FRAMES == 0:
        # analizar a resolucion reducida para reducir el lag; luego se escalan las coordenadas
        pequeno = cv2.resize(frame, (0, 0), fx=ESCALA, fy=ESCALA)
        # face_recognition espera imagenes en RGB, pero OpenCV captura en BGR
        rgb = cv2.cvtColor(pequeno, cv2.COLOR_BGR2RGB)

        ubicaciones = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, ubicaciones)
        # las coordenadas se calcularon sobre la imagen reducida; se reescalan para
        # que encajen con el frame original (a tamano completo) al dibujar
        ubicaciones = [
            (int(top / ESCALA), int(right / ESCALA), int(bottom / ESCALA), int(left / ESCALA))
            for (top, right, bottom, left) in ubicaciones
        ]

    encoding_desconocido = None  # el primer desconocido del frame, para poder registrarlo

    # zip empareja cada ubicacion con su encoding correspondiente (misma posicion en
    # las dos listas = misma cara); se recorre una vez por cada cara detectada en el frame
    for (top, right, bottom, left), encoding in zip(ubicaciones, encodings):
        nombre_detectado = "Desconocido"
        persona_id = None

        if encodings_conocidos:
            # distancia (cuanto se parecen) entre esta cara y cada una de las conocidas;
            # cuanto mas baja, mas se parecen. Nos quedamos con la mas parecida de todas
            distancias = face_recognition.face_distance(encodings_conocidos, encoding)
            mejor = distancias.argmin()
            if distancias[mejor] <= TOLERANCIA:
                nombre_detectado = nombres[mejor]
                persona_id = ids[mejor]

        color = (0, 255, 0) if persona_id else (0, 0, 255)  # verde = reconocido, rojo = desconocido
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)  # dibuja el recuadro alrededor de la cara
        cv2.putText(frame, nombre_detectado, (left, top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)  # escribe el nombre encima del recuadro

        if persona_id is None:
            if encoding_desconocido is None:
                encoding_desconocido = encoding
            cv2.putText(frame, "pulsa 'r' para registrar", (left, bottom + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        if persona_id is not None:
            ahora = time.time()
            # solo se registra si ha pasado el intervalo desde la ultima vez que se vio
            # a esta persona; si no, cada frame detectado generaria una fila nueva
            if ahora - ultimo_registro.get(persona_id, 0) > INTERVALO_MISMA_PERSONA:
                fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
                foto_path = os.path.join(CARPETA_CAPTURAS, f"{nombre_detectado}_{fecha}.jpg")
                cv2.imwrite(foto_path, frame[top:bottom, left:right])  # guarda el recorte de la cara

                db.registrar_asistencia(conn, persona_id, datetime.now().isoformat(), foto_path)
                print(f"Asistencia registrada: {nombre_detectado} - {fecha}")

                ultimo_registro[persona_id] = ahora

    if modo_registro:
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (50, 50, 50), -1)
        cv2.putText(frame, f"Nombre: {texto_nombre}_ (Enter=guardar, Esc=cancelar)",
                    (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.imshow("Reconocimiento de asistencia", frame)

    tecla = cv2.waitKey(1) & 0xFF

    if modo_registro:
        # mientras se esta escribiendo el nombre, las teclas normales (q, r) no hacen
        # nada especial: se interpretan como texto para el nombre
        if tecla == 13:  # Enter -> guardar
            nombre = texto_nombre.strip()
            if nombre:
                db.guardar_persona(conn, nombre, encoding_pendiente)
                nuevo_id = conn.execute("SELECT id FROM personas WHERE nombre = ?", (nombre,)).fetchone()[0]
                if clase_por_defecto is not None:
                    db.asignar_clase(conn, nuevo_id, clase_por_defecto)
                # se anade tambien a las listas en memoria para reconocerlo desde ya,
                # sin tener que reiniciar el script
                nombres.append(nombre)
                ids.append(nuevo_id)
                encodings_conocidos.append(encoding_pendiente)
                print(f"Persona registrada: {nombre}")
            modo_registro = False
        elif tecla == 27:  # Esc -> cancelar
            modo_registro = False
        elif tecla == 8:  # Backspace -> borrar ultima letra
            texto_nombre = texto_nombre[:-1]
        elif 32 <= tecla < 127:  # cualquier caracter imprimible normal
            texto_nombre += chr(tecla)
    elif tecla == ord('q'):
        break
    elif tecla == ord('r') and encoding_desconocido is not None:
        # entra en modo alta usando el encoding de la primera cara desconocida de este frame
        modo_registro = True
        texto_nombre = ""
        encoding_pendiente = encoding_desconocido

cap.release()
cv2.destroyAllWindows()
