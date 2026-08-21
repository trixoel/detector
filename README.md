# Detector — Control de asistencia por reconocimiento facial

Sistema de automatización del control de asistencia mediante visión artificial:
la cámara detecta y reconoce caras, registra la asistencia en una base de datos,
y una web permite consultarla, gestionar horarios y justificar faltas (con
portal propio para las familias).

## Estructura del proyecto

| Archivo / carpeta        | Qué hace |
|---------------------------|----------|
| `reconocer.py`             | Abre la cámara, detecta y reconoce caras en directo, registra asistencia. Pulsa `r` para dar de alta a alguien nuevo desde la propia cámara. |
| `registrar_persona.py`     | Da de alta a alguien a partir de una foto ya existente (`python registrar_persona.py "Nombre" foto.jpg`). |
| `app.py`                   | Web (Flask): vista del profesor (asistencia, horario, alumnado, alertas) y portal de familias con login. |
| `db.py`                    | Acceso a la base de datos SQLite (`asistencia.db`, se crea sola al primer uso). |
| `templates/`               | Plantillas HTML de la web. |
| `caras_detectadas/`, `fotos/`, `justificantes/` | Fotos capturadas y justificantes subidos. **No se suben a git** (datos personales). |

## Instalación

Requiere Python 3.10+ (probado en 3.14).

```bash
pip install -r requirements.txt
```

Aviso: `dlib` no tiene wheel precompilado para Python 3.14, así que `pip`
lo compilará desde código fuente la primera vez (necesita `cmake`, que se
instala solo, y un compilador C++ — en Windows, Visual Studio Build Tools).
Puede tardar varios minutos.

## Primer uso

La base de datos se crea vacía. Antes de usar la cámara hace falta al menos
una clase con horario:

```python
import db
conn = db.conectar()
db.crear_clase(conn, "2 Bachillerato Tecnologico de Excelencia", "08:15")
clase_id = conn.execute("SELECT id FROM clases").fetchone()[0]
db.guardar_horario(conn, clase_id, 0, "08:15", "09:10", "Matematicas II")  # dia_semana: 0=lunes .. 4=viernes
# ... repetir por cada tramo/dia
```

Luego, para dar de alta alumnos, dos opciones:
- En directo: ejecuta `reconocer.py`, pon la cara delante de la cámara y pulsa `r`.
- Desde foto: `python registrar_persona.py "Nombre" foto.jpg`.

Los alumnos registrados por cámara se asignan automáticamente a la primera
clase que exista.

## Uso diario

Arrancar los dos procesos (cada uno en su propia terminal):

```bash
python app.py         # web en http://127.0.0.1:5000
python reconocer.py   # ventana de la camara
```

- **Vista del profesor** (`/`, `/horario`, `/alumnado`, `/alertas`): asistencia
  del día por asignatura, horario semanal, listado de alumnos y registro de
  alertas (se generan solas cuando termina una clase sin que se detecte al
  alumno).
- **Portal de familias** (`/padres/registro` para crear cuenta, luego
  `/padres/login`): cada familia ve solo a su hijo/a, sus faltas agrupadas
  por día, y puede justificarlas adjuntando un archivo (PDF/JPG/PNG).

## Notas

- La cámara en Windows usa el backend DirectShow (`cv2.CAP_DSHOW`); si falla
  al abrir, comprueba que ningún otro proceso la tenga abierta.
- `asistencia.db`, las fotos y los justificantes contienen datos personales
  y biométricos reales — están en `.gitignore` a propósito, no los subas a
  un repositorio público.
- La clave de sesión de Flask (`app.secret_key` en `app.py`) es de
  desarrollo; cámbiala antes de usar esto en producción.
