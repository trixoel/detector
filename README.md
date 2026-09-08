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
| `seed_datos.py`            | Comprueba que la clase y el horario de partida existen (se crean solos, ver "Primer uso"); opcional, solo para confirmarlo a mano. |
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

La base de datos se crea sola, con la clase por defecto y su horario semanal
ya cargados (ver `db.asegurar_clase_por_defecto`), la primera vez que arranca
`app.py` o `reconocer.py` — no hay que ejecutar nada a mano. Para cambiar el
nombre de la clase o las asignaturas, edita las constantes `NOMBRE_CLASE_DEFECTO`
/ `HORARIO_SEMANAL_DEFECTO` al principio de `db.py`.

Para dar de alta alumnos, dos opciones:
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
  al abrir, comprueba que ningún otro proceso la tenga abierta. Este backend
  es específico de Windows: en Mac/Linux hay que quitar `cv2.CAP_DSHOW` de
  `cv2.VideoCapture(0, cv2.CAP_DSHOW)` en `reconocer.py` (dejar solo `cv2.VideoCapture(0)`).
- Todos los scripts usan rutas relativas (`asistencia.db`, `caras_detectadas/`,
  `justificantes/`), así que hay que ejecutarlos siempre desde dentro de la
  carpeta del proyecto (`cd detector` antes de cualquier `python ...`).
- `asistencia.db`, las fotos y los justificantes contienen datos personales
  y biométricos reales — están en `.gitignore` a propósito, no los subas a
  un repositorio público.
- La clave de sesión de Flask (`app.secret_key` en `app.py`) es de
  desarrollo; cámbiala antes de usar esto en producción.
