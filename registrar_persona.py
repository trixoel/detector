import sys
import face_recognition
import db

if len(sys.argv) != 3:
    print("Uso: python registrar_persona.py \"Nombre Apellido\" ruta_foto.jpg")
    sys.exit(1)

nombre = sys.argv[1]
ruta_foto = sys.argv[2]

imagen = face_recognition.load_image_file(ruta_foto)
encodings = face_recognition.face_encodings(imagen)

if not encodings:
    print(f"No se detecto ninguna cara en {ruta_foto}")
    sys.exit(1)
if len(encodings) > 1:
    print(f"Se detectaron {len(encodings)} caras, usa una foto con una sola persona")
    sys.exit(1)

conn = db.conectar()
db.guardar_persona(conn, nombre, encodings[0])
print(f"Persona registrada: {nombre}")
