# Da de alta a una persona en la base de datos a partir de UNA foto ya existente
# (a diferencia de reconocer.py, que la registra en directo desde la camara).
# Uso: python registrar_persona.py "Nombre Apellido" ruta_foto.jpg
import sys
import face_recognition
import db

# hace falta exactamente 2 argumentos ademas del nombre del script: nombre y ruta de la foto
if len(sys.argv) != 3:
    print("Uso: python registrar_persona.py \"Nombre Apellido\" ruta_foto.jpg")
    sys.exit(1)

nombre = sys.argv[1]
ruta_foto = sys.argv[2]

imagen = face_recognition.load_image_file(ruta_foto)
# face_encodings calcula, para cada cara que encuentra en la foto, un vector de 128
# numeros (su "huella facial"); eso es lo que luego se compara para reconocer a alguien
encodings = face_recognition.face_encodings(imagen)

if not encodings:
    print(f"No se detecto ninguna cara en {ruta_foto}")
    sys.exit(1)
if len(encodings) > 1:
    # con mas de una cara no sabriamos a cual de las dos asignarle el nombre dado
    print(f"Se detectaron {len(encodings)} caras, usa una foto con una sola persona")
    sys.exit(1)

conn = db.conectar()
db.guardar_persona(conn, nombre, encodings[0])
print(f"Persona registrada: {nombre}")
