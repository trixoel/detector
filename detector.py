import cv2
import os
import time
from datetime import datetime

# Crear carpeta donde guardar las fotos
carpeta = "caras_detectadas"
if not os.path.exists(carpeta):
    os.makedirs(carpeta)

# Cargar detector de caras
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# Iniciar cámara
cap = cv2.VideoCapture(0)

ultimo_guardado = 0
intervalo = 2  # segundos entre fotos

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Detectar caras
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)

    for (x, y, w, h) in faces:
        # Dibujar rectángulo (solo visual)
        cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)

        # Guardar cada cierto tiempo
        if time.time() - ultimo_guardado > intervalo:
            cara = frame[y:y+h, x:x+w]

            fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(carpeta, f"cara_{fecha}.jpg")

            cv2.imwrite(filename, cara)
            print(f"Foto guardada: {filename}")

            ultimo_guardado = time.time()

    # Mostrar cámara
    cv2.imshow("Detector de caras", frame)

    # Salir con 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Liberar recursos
cap.release()
cv2.destroyAllWindows()