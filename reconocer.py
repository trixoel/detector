import cv2
import face_recognition
import os
import time
from datetime import datetime

import db

TOLERANCIA = 0.6  # menor = mas estricto
INTERVALO_MISMA_PERSONA = 30  # segundos entre registros de la misma persona
CARPETA_CAPTURAS = "caras_detectadas"

os.makedirs(CARPETA_CAPTURAS, exist_ok=True)

conn = db.conectar()
personas = db.obtener_personas(conn)
if not personas:
    print("No hay personas registradas. Usa registrar_persona.py primero.")

clases = db.listar_clases(conn)
clase_por_defecto = clases[0][0] if clases else None
if clase_por_defecto is None:
    print("Aviso: no hay ninguna clase creada, los nuevos registros no se veran en la web hasta crear una.")

nombres = [p[1] for p in personas]
ids = [p[0] for p in personas]
encodings_conocidos = [p[2] for p in personas]

ultimo_registro = {}  # persona_id -> timestamp del ultimo registro

modo_registro = False
texto_nombre = ""
encoding_pendiente = None

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

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
        rgb = cv2.cvtColor(pequeno, cv2.COLOR_BGR2RGB)

        ubicaciones = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, ubicaciones)
        ubicaciones = [
            (int(top / ESCALA), int(right / ESCALA), int(bottom / ESCALA), int(left / ESCALA))
            for (top, right, bottom, left) in ubicaciones
        ]

    encoding_desconocido = None  # el primer desconocido del frame, para poder registrarlo

    for (top, right, bottom, left), encoding in zip(ubicaciones, encodings):
        nombre_detectado = "Desconocido"
        persona_id = None

        if encodings_conocidos:
            distancias = face_recognition.face_distance(encodings_conocidos, encoding)
            mejor = distancias.argmin()
            if distancias[mejor] <= TOLERANCIA:
                nombre_detectado = nombres[mejor]
                persona_id = ids[mejor]

        color = (0, 255, 0) if persona_id else (0, 0, 255)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, nombre_detectado, (left, top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        if persona_id is None:
            if encoding_desconocido is None:
                encoding_desconocido = encoding
            cv2.putText(frame, "pulsa 'r' para registrar", (left, bottom + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        if persona_id is not None:
            ahora = time.time()
            if ahora - ultimo_registro.get(persona_id, 0) > INTERVALO_MISMA_PERSONA:
                fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
                foto_path = os.path.join(CARPETA_CAPTURAS, f"{nombre_detectado}_{fecha}.jpg")
                cv2.imwrite(foto_path, frame[top:bottom, left:right])

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
        if tecla == 13:  # Enter
            nombre = texto_nombre.strip()
            if nombre:
                db.guardar_persona(conn, nombre, encoding_pendiente)
                nuevo_id = conn.execute("SELECT id FROM personas WHERE nombre = ?", (nombre,)).fetchone()[0]
                if clase_por_defecto is not None:
                    db.asignar_clase(conn, nuevo_id, clase_por_defecto)
                nombres.append(nombre)
                ids.append(nuevo_id)
                encodings_conocidos.append(encoding_pendiente)
                print(f"Persona registrada: {nombre}")
            modo_registro = False
        elif tecla == 27:  # Esc
            modo_registro = False
        elif tecla == 8:  # Backspace
            texto_nombre = texto_nombre[:-1]
        elif 32 <= tecla < 127:
            texto_nombre += chr(tecla)
    elif tecla == ord('q'):
        break
    elif tecla == ord('r') and encoding_desconocido is not None:
        modo_registro = True
        texto_nombre = ""
        encoding_pendiente = encoding_desconocido

cap.release()
cv2.destroyAllWindows()
