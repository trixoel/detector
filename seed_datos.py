# Ya NO hace falta ejecutar este script a mano: db.conectar() crea la clase y el horario
# de partida automaticamente la primera vez que se usa la base de datos (ver
# db.asegurar_clase_por_defecto), tanto en la version normal como en la compilada (.exe).
# Este script se mantiene solo como comprobacion rapida: ejecutalo si quieres confirmar
# que la clase quedo bien creada, o justo despues de borrar asistencia.db.
import db

conn = db.conectar()
clase_id, nombre, hora_entrada = db.listar_clases(conn)[0]
total_tramos = conn.execute("SELECT COUNT(*) FROM horario WHERE clase_id = ?", (clase_id,)).fetchone()[0]

print(f"Clase '{nombre}' lista (id={clase_id}), {total_tramos} tramos de horario.")
print("Ahora da de alta alumnos con 'r' en reconocer.py, o con registrar_persona.py.")
