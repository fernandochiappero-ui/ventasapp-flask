# init_db.py
#
# Script que se ejecuta UNA sola vez (o cada vez que quieras empezar
# de cero) para:
#   1) Crear el archivo de base de datos con todas las tablas.
#   2) Crear un usuario administrador para poder loguearte.
#
# Se ejecuta desde la terminal con:  python init_db.py

import os
from getpass import getpass

from app import create_app
from extensions import db
from models import Usuario

app = create_app()

with app.app_context():
    # Flask-SQLAlchemy guarda SQLite en app.instance_path.
    os.makedirs(app.instance_path, exist_ok=True)

    db.create_all()
    print("Tablas creadas (o ya existían).")

    if Usuario.query.count() == 0:
        print("\nNo hay usuarios todavía. Creemos el primer usuario:")
        username = input("Nombre de usuario [admin]: ").strip() or "admin"
        password = getpass("Contraseña: ").strip()
        while not password:
            password = getpass(
                "La contraseña no puede estar vacía. Contraseña: "
            ).strip()

        usuario = Usuario(username=username)
        usuario.set_password(password)
        db.session.add(usuario)
        db.session.commit()
        print(f"\nUsuario '{username}' creado. Ya podés iniciar sesión.")
    else:
        print("Ya existen usuarios, no se creó ninguno nuevo.")
